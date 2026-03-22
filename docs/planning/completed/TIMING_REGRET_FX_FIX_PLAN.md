# Fix Timing Regret Currency Mixing Bug

## Context

`total_regret` sums `regret_dollars` across currencies without FX conversion. MHI's HKD 41,392 regret gets added directly to USD amounts, inflating total_regret from ~$5,400 to ~$46,000.

## Root Cause

`TimingResult` has no USD variants for P&L fields (unlike `TradeResult` which has `pnl_dollars` + `pnl_dollars_usd`). The `analyze_timing()` function computes all P&L in local currency and never applies FX conversion.

## Plan

### 1. Add USD fields to TimingResult

**File:** `trading_analysis/models.py`

Add defaulted USD fields (won't break existing constructors):
```python
@dataclass
class TimingResult:
    # ... existing fields ...
    actual_pnl_usd: float = 0.0
    best_case_pnl_usd: float = 0.0
    worst_case_pnl_usd: float = 0.0
    regret_dollars_usd: float = 0.0
```

Add to `to_dict()`:
```python
'actual_pnl_usd': round(self.actual_pnl_usd, 2),
'best_case_pnl_usd': round(self.best_case_pnl_usd, 2),
'worst_case_pnl_usd': round(self.worst_case_pnl_usd, 2),
'regret_dollars_usd': round(self.regret_dollars_usd, 2),
```

### 2. Apply FX conversion in analyze_timing()

**File:** `trading_analysis/analyzer.py`

After building each TimingResult, apply FX conversion using `self._fx_rates` (already stored from sizing work):

```python
fx_rate = self._fx_rates.get((rt.currency or "USD").upper(), 1.0)
timing_result.actual_pnl_usd = timing_result.actual_pnl * fx_rate
timing_result.best_case_pnl_usd = timing_result.best_case_pnl * fx_rate
timing_result.worst_case_pnl_usd = timing_result.worst_case_pnl * fx_rate
timing_result.regret_dollars_usd = timing_result.regret_dollars * fx_rate
```

### 3. Sum total_regret in USD

**File:** `trading_analysis/analyzer.py` — `run_full_analysis()`

```python
# Before:
total_regret = sum(t.regret_dollars for t in timing_results)

# After:
total_regret = sum(t.regret_dollars_usd for t in timing_results)
```

### 4. Update agent snapshot

**File:** `trading_analysis/models.py` — `get_agent_snapshot()`

`total_regret` is already emitted from `self.total_regret` — no change needed since the value is now USD-converted at the source.

### 5. Flag threshold unchanged

**File:** `core/trading_flags.py`

`high_regret` flag checks `total_regret > 1000`. Now that total_regret is in USD, the $1,000 threshold is correct (it was implicitly assuming USD before).

### 6. Fix filter_by_date_range()

**File:** `trading_analysis/models.py` — `filter_by_date_range()` (~line 691)

This method recomputes `self.total_regret` from timing results. Update to use USD:

```python
# Before:
self.total_regret = sum(t.regret_dollars for t in self.timing_results)

# After:
self.total_regret = sum(t.regret_dollars_usd for t in self.timing_results)
```

### 7. Sort timing results by USD regret

**File:** `trading_analysis/analyzer.py` — `analyze_timing()` return

Sort timing results by `regret_dollars_usd` (not local) so cross-currency ranking is correct:

```python
timing_results.sort(key=lambda t: t.regret_dollars_usd, reverse=True)
```

### 8. CLI report uses USD regret throughout

**File:** `trading_analysis/models.py` — `to_cli_report()` "Top Regret" section (~line 1184)

Update ALL regret references in the report to use USD:
- Sort by `regret_dollars_usd` (not local `regret_dollars`)
- The `>100000` skip filter uses `regret_dollars_usd`
- Display value uses `regret_dollars_usd`

### 9. TimingResult USD fallback

For TimingResult objects constructed without explicit USD fields (test fixtures, direct construction), add a property that falls back to local currency when USD is 0:

Apply fallback in `to_dict()` — emit local currency value when USD is 0 (for backward compat with direct constructors):

```python
def to_dict(self):
    return {
        ...
        'actual_pnl_usd': round(self.actual_pnl_usd or self.actual_pnl, 2),
        'best_case_pnl_usd': round(self.best_case_pnl_usd or self.best_case_pnl, 2),
        'worst_case_pnl_usd': round(self.worst_case_pnl_usd or self.worst_case_pnl, 2),
        'regret_dollars_usd': round(self.regret_dollars_usd or self.regret_dollars, 2),
    }
```

For aggregation (filter_by_date_range, total_regret sum), use the same pattern: `t.regret_dollars_usd or t.regret_dollars`. This way test fixtures that don't set USD fields still produce reasonable values without needing updates.

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/models.py` | Add 4 USD fields to TimingResult + to_dict() with fallback. Fix filter_by_date_range() to sum USD. Fix CLI report sort/filter/display to use USD. |
| `trading_analysis/analyzer.py` | FX-convert timing P&L after construction, sum regret_dollars_usd, sort by USD regret |
| `trading_analysis/main.py` | Update CLI JSON timing serializer (~line 154) to include USD timing fields |
| `tests/trading_analysis/test_result_serialization.py` | Update TimingResult fixtures with USD fields or verify fallback |
| `tests/trading_analysis/test_date_filter.py` | Update TimingResult fixtures with USD fields or verify fallback |

## Tests

- MHI (HKD) timing: regret_dollars in HKD, regret_dollars_usd converted
- USD timing: regret_dollars == regret_dollars_usd (rate 1.0)
- total_regret sums USD values only
- Mixed HKD + USD: total_regret is pure USD
- high_regret flag uses USD total_regret

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP: total_regret should be ~$5,400 (not $46,000)
3. Flag: high_regret should still fire (>$1,000 even in USD)
4. CLI JSON (main.py not import-safe, verify manually):
   `python trading_analysis/main.py --json-only | python -c "import sys,json; d=json.load(sys.stdin); [print(t.get('regret_dollars_usd')) for t in d.get('timing_analysis',[])]"`
