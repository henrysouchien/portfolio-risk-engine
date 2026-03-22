# Post-Exit Analysis — "Should I Have Held Longer?"

## Context

Current timing measures exit quality within the holding period. This new analysis looks at what happened AFTER you sold — did the stock keep running or did you exit at the right time?

Three windows, each informing a different level of the investment process:
- **30 days**: Tactical — did I miss a short-term move?
- **90 days**: Position management — am I cutting trends short?
- **12 months**: Thesis conviction — should I trust my research more and hold longer?

## Design

### Per round-trip: compute post-exit returns

For each closed round-trip with enough post-exit history:

```python
# Fetch closes for exit_date + 385 days (365 + 20 tolerance buffer)
post_exit_closes = provider.fetch_daily_close(
    symbol, start_date=exit_date, end_date=exit_date + 385 days,
    instrument_type=..., contract_identity=...,
)

# Target-date lookup with adaptive tolerance (±5 daily, ±20 monthly)
def _detect_cadence(closes: pd.Series) -> str:
    """Detect whether a price series is daily or monthly from the data."""
    if len(closes) < 2:
        return "unknown"
    median_gap = closes.index.to_series().diff().dt.days.median()
    return "monthly" if median_gap > 20 else "daily"

def _lookup_price_near(closes: pd.Series, target_date: date, cadence: str) -> tuple[float | None, str | None]:
    """Find closest available close price to target_date.

    cadence="daily": ±5 days tolerance
    cadence="monthly" or "unknown": ±20 days tolerance (conservative)
    """
    tolerance_days = 5 if cadence == "daily" else 20

    start = pd.Timestamp(target_date - timedelta(days=tolerance_days))
    end = pd.Timestamp(target_date + timedelta(days=tolerance_days))
    window = closes.loc[start:end]
    if window.empty:
        return None, None
    target_ts = pd.Timestamp(target_date)
    closest_idx = (window.index - target_ts).abs().argmin()
    return float(window.iloc[closest_idx]), str(window.index[closest_idx].date())

cadence = _detect_cadence(post_exit_closes)  # detect once per symbol from the actual data
price_30d, date_30d = _lookup_price_near(post_exit_closes, exit_date + 30 days, cadence)
price_90d, date_90d = _lookup_price_near(post_exit_closes, exit_date + 90 days, cadence)
price_12m, date_12m = _lookup_price_near(post_exit_closes, exit_date + 365 days, cadence)

# Compute returns (direction-aware)
if direction == "LONG":
    post_exit_return_30d = (price_30d - exit_price) / exit_price × 100
    post_exit_return_90d = (price_90d - exit_price) / exit_price × 100
    post_exit_return_12m = (price_12m - exit_price) / exit_price × 100
else:  # SHORT — price dropping after you covered = missed opportunity (could have covered cheaper)
    post_exit_return_30d = (exit_price - price_30d) / exit_price × 100
    post_exit_return_90d = (exit_price - price_90d) / exit_price × 100
    post_exit_return_12m = (exit_price - price_12m) / exit_price × 100
```

Positive return = stock moved in your favor after exit (you sold too early).
Negative return = stock moved against after exit (good exit).

### Minimum post-exit history

Only include round-trips with enough post-exit calendar time:
- 30d metric: exit_date + 30 days ≤ today (use calendar days, not trading days — works for monthly-only data too)
- 90d metric: exit_date + 90 days ≤ today
- 12m metric: exit_date + 365 days ≤ today

If the target date passes the calendar check but `_lookup_price_near()` finds no close within tolerance (±5 days for daily, ±20 for monthly), that window is None (data gap).

Round-trips closed recently won't have all three windows. Compute whatever windows are available.

**Monthly-only data note:** For instruments where only monthly data is available (IBKR fallback for futures/options/bonds), 30d and 90d windows may be coarse. The adaptive tolerance (±20 days for monthly) helps find month-end closes near the target date. For monthly data, 12m is the most reliable window; 30d/90d windows will resolve to nearby month-ends (±20 tolerance) but are coarser than daily — the actual sampled date may be up to 20 days from the target.

### Aggregate: split winners and losers

Separate analysis for winning and losing trades — they tell different stories:

**Winners (trades closed at a profit):**
- Avg post-exit return at 30d/90d/12m
- Positive = you're selling winners too early (thesis was right, conviction was weak)
- Negative = good exit (you captured the move)

**Losers (trades closed at a loss):**
- Avg post-exit return at 30d/90d/12m
- Negative = good loss discipline (price kept falling, right to cut)
- Positive = panic selling (price recovered, you sold at the bottom)

### Output: PostExitAnalysis result

```python
@dataclass
class PostExitResult:
    symbol: str
    currency: str
    direction: str
    instrument_type: str
    exit_date: str
    exit_price: float
    was_winner: bool
    # Returns (None if not enough post-exit history or no close within tolerance)
    post_exit_return_30d: float | None
    post_exit_return_90d: float | None
    post_exit_return_12m: float | None
    # Actual prices used
    post_exit_price_30d: float | None
    post_exit_price_90d: float | None
    post_exit_price_12m: float | None
    # Actual dates sampled (so consumers know if "30d" was really day 28 or 32)
    post_exit_date_30d: str | None
    post_exit_date_90d: str | None
    post_exit_date_12m: str | None

@dataclass
class PostExitSummary:
    # Winners — per-window counts (different windows may have different eligible trades)
    winner_count_30d: int = 0
    winner_count_90d: int = 0
    winner_count_12m: int = 0
    winner_avg_post_exit_30d: float | None = None
    winner_avg_post_exit_90d: float | None = None
    winner_avg_post_exit_12m: float | None = None

    # Losers — per-window counts
    loser_count_30d: int = 0
    loser_count_90d: int = 0
    loser_count_12m: int = 0
    loser_avg_post_exit_30d: float | None = None
    loser_avg_post_exit_90d: float | None = None
    loser_avg_post_exit_12m: float | None = None

    # Per-trade detail
    results: list[PostExitResult] = field(default_factory=list)
```

### Insights / flags generated

Based on the aggregates, generate actionable flags:

All flags require minimum 3 trades in the relevant window/cohort to avoid one outlier triggering a behavioral insight.

**Selling winners too early (positive post-exit for winners):**
```python
if winner_count_90d >= 3 and winner_avg_post_exit_90d is not None and winner_avg_post_exit_90d > 5:
    flag("premature_winner_exit", "info",
         f"Your winners gained an avg of {winner_avg_post_exit_90d:.0f}% in the 90 days after you sold — consider holding winners longer")
```

**Good exit discipline for losers (negative post-exit for losers):**
```python
if loser_count_90d >= 3 and loser_avg_post_exit_90d is not None and loser_avg_post_exit_90d < -5:
    flag("good_loss_discipline", "success",
         f"Losers fell an avg of {abs(loser_avg_post_exit_90d):.0f}% after you cut — good discipline")
```

**Panic selling (positive post-exit for losers):**
```python
if loser_count_90d >= 3 and loser_avg_post_exit_90d is not None and loser_avg_post_exit_90d > 10:
    flag("panic_selling", "warning",
         f"Losers recovered an avg of {loser_avg_post_exit_90d:.0f}% after you sold — may be selling at bottoms")
```

**Strong thesis quality (positive post-exit 12m for winners):**
```python
if winner_count_12m >= 3 and winner_avg_post_exit_12m is not None and winner_avg_post_exit_12m > 15:
    flag("strong_thesis_weak_conviction", "info",
         f"Your winners gained an avg of {winner_avg_post_exit_12m:.0f}% in the 12 months after you sold — your thesis picks are strong, consider higher conviction holds")
```

### Price fetching — same provider chain as timing

Use the same approach from timing analysis:
- Provider chain via `registry.get_price_chain(instrument_type)`
- Daily then monthly fallback
- FMP for equities/futures, IBKR for options/bonds
- FX conversion via `self._fx_rates`
- Skip symbols where no provider returns data

Group by `(symbol, currency, instrument_type)` to share price fetches. Same contract_identity limitation as timing: different contracts for the same root symbol share one fetch. Accepted as v1 limitation.

Since timing already fetches prices for the holding period, post-exit analysis can extend the same fetch window to `exit_date + 385 days` (365 + 20 tolerance buffer) to cover both in one call per symbol.

### Where this lives

**Option A**: Inside `analyze_timing()` — extend the price fetch and compute post-exit alongside timing.
**Option B**: Separate `analyze_post_exit()` method — cleaner separation of concerns.

**Recommendation:** Option B. Post-exit analysis is a distinct concept from within-period timing. Separate method, separate results, separate flags. But it can share the provider chain setup and price cache.

### Integration

- New method: `TradingAnalyzer.analyze_post_exit(round_trips) -> PostExitSummary`
- Called from `run_full_analysis()` after timing
- Results stored on `FullAnalysisResult` as `post_exit_summary: PostExitSummary | None = None` (defaulted)
- Emitted in `get_agent_snapshot()`, `to_api_response()`, `to_summary()`
- Cleared in `filter_by_date_range()` — `self.post_exit_summary = None`
- Flags generated via new function in `core/trading_flags.py`

### Not a grade dimension

Post-exit analysis produces insights/flags, not a letter grade. It's behavioral feedback:
- "You're selling winners too early" (actionable)
- "Your loss discipline is good" (reinforcement)
- "Your thesis picks are strong but your conviction is weak" (strategic)

These complement the existing 4-dimension scorecard (Edge, Sizing, Timing, Discipline) without adding a 5th grade.

### Frontend integration

Post-exit flags flow through the existing `flags` array in the API response / agent snapshot. The TradingPnLCard's Insights section already renders the top 3 non-success flags — post-exit flags (premature_winner_exit, panic_selling, etc.) will appear automatically alongside existing flags like "conviction misaligned" and "high regret." No frontend code change needed for v1.

Detailed per-window breakdown (tables, per-trade post-exit returns) is a follow-up if the flags prove useful on real data.

## Files to Change

| File | Change |
|------|--------|
| `trading_analysis/models.py` | PostExitResult + PostExitSummary dataclasses, add to FullAnalysisResult |
| `trading_analysis/analyzer.py` | `analyze_post_exit()` method, wire into `run_full_analysis()` |
| `core/trading_flags.py` | Post-exit flags (premature_winner_exit, good_loss_discipline, panic_selling, strong_thesis_weak_conviction) |
| `trading_analysis/models.py` | Emit in get_agent_snapshot, to_api_response, to_summary, clear in filter_by_date_range |
| `tests/trading_analysis/test_agent_snapshot.py` | Assert post_exit_summary in snapshot |
| `tests/trading_analysis/test_result_serialization.py` | Assert post_exit_summary in API response |

## Tests

- 3+ winners with positive post-exit 90d avg → "selling winners too early" flag
- 3+ losers with negative post-exit 90d avg → "good loss discipline" flag
- 3+ losers with positive post-exit 90d avg → "panic selling" flag
- 1-2 winners with positive post-exit → no flag (below minimum sample)
- Round-trip closed < 30 days ago → 30d metric None
- Round-trip closed < 90 days ago → 90d metric None
- Provider returns no post-exit data → skip
- Short positions: post-exit return inverted correctly
- Winners and losers aggregated separately
- _lookup_price_near: target date with no close within adaptive tolerance → None
- _lookup_price_near: target on weekend → picks closest weekday
- Sampled dates (post_exit_date_30d etc.) populated correctly in PostExitResult
- Per-window cohort counts (winner_count_30d vs winner_count_12m may differ)
- filter_by_date_range() clears post_exit_summary to None
- Flag minimum sample: <3 trades in window → no flag even if avg exceeds threshold
- post_exit_summary appears in agent snapshot (test_agent_snapshot.py)
- post_exit_summary appears in API response (test_result_serialization.py)
- post_exit_summary appears in summary output
- Monthly data: ±20 day adaptive tolerance → price found near month-end
- Daily data: ±5 day tolerance → closest trading day

## Verification

1. `pytest tests/trading_analysis/ tests/core/test_trading_flags.py -v` — all tests pass
2. MCP: post_exit_summary appears in agent snapshot
3. Live: check if any post-exit flags fire for the portfolio
