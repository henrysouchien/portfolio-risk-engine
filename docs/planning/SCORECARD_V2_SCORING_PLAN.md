# Scorecard v2 — Scoring Functions

## Context

Round-trip aggregation is live (committed `ac31c9b7`). The FIFO matcher now emits `RoundTrip` objects on `FIFOMatcherResult.round_trips`. Verified on live data: 42 lots → 16 round-trips.

This step adds the three new grading functions and replaces the old grades in-place. No dual-write — old dimension names (conviction, position_sizing, averaging_down) are replaced by new ones (edge, sizing, discipline). Timing stays.

## Prerequisite: Store FIFO matcher result in analyzer

**File:** `trading_analysis/analyzer.py`

Initialize `_fifo_matcher_result = None` in `__init__()`. Reset at top of `run_full_analysis()`. Set in `_analyze_trades_fifo()`:

```python
# In __init__():
self._fifo_matcher_result: Optional[FIFOMatcherResult] = None

# In _analyze_trades_fifo():
self._fifo_matcher_result = result  # store for grading

# In run_full_analysis(), at top:
self._fifo_matcher_result = None  # reset before each run
```

**`use_fifo=False` (averaged mode):** Legacy fallback, not used in production. In averaged mode, `_fifo_matcher_result` is never set, so round_trips is empty and Edge/Sizing/Discipline grades default to N/A. Timing still works (it uses raw trades, not round-trips). Overall grade will be N/A (< 2 dimensions available unless timing has data, in which case it's the only grade and still N/A overall).

## Scoring Functions

### 1. compute_edge_grade()

**Input:** `round_trips: list[RoundTrip]`

**Logic:**
1. Filter out synthetic round-trips
2. Exclude non-tradeable types: instrument_type in ("fx", "fx_artifact", "income")
3. Group remaining by instrument class:
   - equity: instrument_type in ("equity", "mutual_fund", "bond", "unknown")
   - option: instrument_type == "option"
   - futures: instrument_type == "futures"
4. Drop classes with < 3 round-trips
5. Count total gradeable round-trips (sum of remaining class counts). If < 10 → "N/A"
6. Per qualifying class: compute mean of `rt.pnl_percent`, map to grade:

| Grade | Equity | Options | Futures |
|-------|--------|---------|---------|
| A | ≥ 5% | ≥ 20% | ≥ 8% |
| B | ≥ 2% | ≥ 8% | ≥ 3% |
| C | ≥ 0% | ≥ 0% | ≥ 0% |
| D | ≥ -3% | ≥ -10% | ≥ -5% |
| F | < -3% | < -10% | < -5% |

7. Single qualifying class → that class's grade
8. Multiple classes → weighted GPA by round-trip count → letter (≥ 3.5 → A, ≥ 2.5 → B, ≥ 1.5 → C, ≥ 0.5 → D, else F)

### 2. compute_discipline_grade()

**Input:** `round_trips: list[RoundTrip]`

Composite of two behavioral sub-metrics. Each maps to 0-100, then weighted average → grade.

**a) Patience (50%) — do you hold winners longer than losers?**
1. Filter out synthetic round-trips
2. Split into winners and losers
3. If < 5 total OR no winners OR no losers → sub-score excluded
4. Exclude round-trips with `days_in_trade == 0`. If either group becomes empty → excluded
5. Patience ratio = median_winner_hold / median_loser_hold
6. Score = round(50 + 36.1 × ln(clamp(ratio, 0.2, 5.0)))

**b) Revenge trading (50%) — do you re-enter after losses?**

Detection: Compare consecutive round-trips for the same `(symbol, currency, direction)` key. If round-trip N closed at a loss and round-trip N+1 for the same key started within 3 calendar days of N's exit → revenge trade.

Implementation: After `aggregate_to_round_trips()`, group round-trips by key, sort by entry_date, and check gaps:
```python
def detect_revenge_trades(round_trips: list[RoundTrip]) -> list[dict]:
    """Returns list of revenge trade events. Input must be pre-filtered to non-synthetic only."""
    by_key = defaultdict(list)
    for rt in round_trips:
        by_key[(rt.symbol, rt.currency, rt.direction)].append(rt)

    revenge_events = []
    for key, rts in by_key.items():
        rts_sorted = sorted(rts, key=lambda r: r.entry_date)
        for i in range(1, len(rts_sorted)):
            prev = rts_sorted[i - 1]
            curr = rts_sorted[i]
            gap_days = (curr.entry_date.date() - prev.exit_date.date()).days  # use .date() to avoid timestamp issues
            if not prev.is_winner and 0 <= gap_days <= 3:
                revenge_events.append({
                    "symbol": curr.symbol,
                    "entry_date": str(curr.entry_date.date()),
                    "gap_days": gap_days,
                })
    return revenge_events
```

**Important:** Filter synthetic round-trips BEFORE calling this function. The caller passes only non-synthetic round-trips so both numerator and denominator are consistent.

Wire into `BehavioralAnalysis.revenge_trades` (which is a `list`) to replace the hardcoded `[]`. The snapshot reads `len(behavioral.revenge_trades)` for `revenge_trade_count`.

Score: `revenge_rate = len(revenge_events) / len(non_synthetic_round_trips)`. Map to 0-100:
- 0% revenge rate → 100 points
- Each 5% deducts 25 points
- Score = max(0, 100 - revenge_rate * 500)

If < 5 round-trips → sub-score excluded.

**Wire into behavioral snapshot:** The new revenge count from `detect_revenge_trades()` should replace the hardcoded `[]` in `analyzer.py ~line 1000`. Update `BehavioralAnalysis.revenge_trades` with the detected events so the agent snapshot's `revenge_trade_count` is accurate. This means flags that read `revenge_trade_count` will also start working.

**Composite scoring:**
- Both sub-scores require ≥ 5 non-synthetic round-trips. If < 5 total → entire Discipline = "N/A"
- Weighted average of available sub-scores (50/50)
- If no sub-scores available → "N/A"
- If only one sub-score → that score alone determines the grade

**Grade thresholds:**
| Grade | Score |
|-------|-------|
| A | ≥ 75 |
| B | ≥ 55 |
| C | ≥ 35 |
| D | ≥ 20 |
| F | < 20 |

### 3. compute_sizing_grade()

**Input:** `round_trips: list[RoundTrip]`

**Logic:**
1. Filter out synthetic round-trips
2. Exclude futures, fx, fx_artifact, income round-trips
3. If < 15 remaining → "N/A"
4. Extract: (abs(rt.cost_basis), rt.pnl_percent)
5. If < 4 distinct cost_basis values → "N/A"
6. If all pnl_percent equal → "N/A"
7. Spearman: `scipy.stats.spearmanr(sizes, returns)` (scipy in requirements.txt)
8. Map: A ≥ 0.25, B ≥ 0.10, C ≥ -0.05, D ≥ -0.20, F < -0.20

### 4. compute_timing_grade()

Replace existing `_get_timing_grade()` with v2 thresholds:

```python
def compute_timing_grade(avg_timing_pct: float | None, timing_symbol_count: int) -> str:
    if timing_symbol_count < 3 or avg_timing_pct is None:
        return "N/A"
    if avg_timing_pct >= 70: return "A"
    if avg_timing_pct >= 55: return "B"
    if avg_timing_pct >= 40: return "C"
    if avg_timing_pct >= 25: return "D"
    return "F"
```

## Integration: Replace grades in-place

### File: `trading_analysis/models.py` — FullAnalysisResult

**Replace scalar grade fields** (lines 609-613):

```python
# Old:
conviction_grade: str = ""
timing_grade: str = ""
position_sizing_grade: str = ""
averaging_down_grade: str = ""
overall_grade: str = ""

# New:
edge_grade: str = ""
sizing_grade: str = ""
timing_grade: str = ""       # same name, kept
discipline_grade: str = ""
overall_grade: str = ""      # same name, kept
```

**Update `filter_by_date_range()`** (~line 697): Clear new field names instead of old ones.

**Update `get_agent_snapshot()`** (~line 772): Change the grades dict construction:
```python
"grades": {
    "overall": self.overall_grade,
    "edge": self.edge_grade,
    "sizing": self.sizing_grade,
    "timing": self.timing_grade,
    "discipline": self.discipline_grade,
},
```

**Update `_GRADE_VERDICT`** (~line 765): `verdict` reads `self.overall_grade` — field name unchanged, no change needed.

**Update `to_api_response()`** (~line 885): Same grades dict change.

**Update `to_summary()`** (~line 952): Same grades dict change.

### File: `trading_analysis/analyzer.py` — `run_full_analysis()`

Replace the existing grading block (~lines 1060-1160) which computes conviction_grade, position_sizing_grade, averaging_down_grade:

```python
round_trips = self._fifo_matcher_result.round_trips if self._fifo_matcher_result else []

edge_grade = compute_edge_grade(round_trips)
discipline_grade = compute_discipline_grade(round_trips)  # uses round-trips only (patience + revenge)
sizing_grade = compute_sizing_grade(round_trips)
timing_grade = compute_timing_grade(avg_timing, timing_symbol_count=len(timing_results))

grade_points = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
available = [grade_points[g] for g in [edge_grade, sizing_grade, timing_grade, discipline_grade] if g in grade_points]
if len(available) >= 2:
    gpa = sum(available) / len(available)
    overall = "A" if gpa >= 3.5 else "B" if gpa >= 2.5 else "C" if gpa >= 1.5 else "D" if gpa >= 0.5 else "F"
else:
    overall = "N/A"
```

Then assign to the FullAnalysisResult:
```python
result.edge_grade = edge_grade
result.sizing_grade = sizing_grade
result.timing_grade = timing_grade
result.discipline_grade = discipline_grade
result.overall_grade = overall
```

### File: `trading_analysis/main.py` — `results_to_dict()`

This serializer hard-codes grade keys (~line 128). Update to emit new keys:
```python
"grades": {
    "overall": results.overall_grade,
    "edge": results.edge_grade,
    "sizing": results.sizing_grade,
    "timing": results.timing_grade,
    "discipline": results.discipline_grade,
},
```

### Frontend

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

Update `subGrades` to read new keys:
```typescript
const subGrades = [
    { label: 'Edge', description: 'Trade selection quality', tooltip: 'Are you picking good trades? Size-neutral average return.', value: grades?.edge || 'N/A' },
    { label: 'Sizing', description: 'Bet sizing vs outcome', tooltip: 'Do your bigger bets outperform your smaller ones?', value: grades?.sizing || 'N/A' },
    { label: 'Timing', description: 'Exit timing', tooltip: 'How close your exits are to optimal sell points', value: grades?.timing || 'N/A' },
    { label: 'Discipline', description: 'Patience & process', tooltip: 'Do you hold winners longer than losers? Do you avoid revenge trading?', value: grades?.discipline || 'N/A' },
]
```

Also update the Overall Grade tooltip (~line 209) from "conviction, timing, sizing, and averaging down" to "edge, sizing, timing, and discipline".

**File:** `frontend/packages/chassis/src/catalog/types.ts`

Update the grades type to use new keys (edge, sizing, discipline) replacing old ones.

### Flags

`generate_trading_flags()` reads `grades["overall"]` from the snapshot — key name unchanged. `verdict` reads `self.overall_grade` — field name unchanged. **No flag changes needed.**

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/analyzer.py` | `_fifo_matcher_result` state, 4 scoring functions (incl. `detect_revenge_trades`), replace grading block, wire revenge events into `BehavioralAnalysis.revenge_trades` |
| `trading_analysis/models.py` | Replace scalar grade fields (conviction→edge, position_sizing→sizing, averaging_down→discipline), update all serializers (`get_agent_snapshot`, `to_api_response`, `to_summary`, `to_cli_report`) + `filter_by_date_range()` |
| `trading_analysis/main.py` | Update `results_to_dict()` + `generate_text_report()` grade keys |
| `docs/reference/DATA_SCHEMAS.md` | Update FullAnalysisResult grade field names |
| `trading_analysis/examples/usage_example.py` | Update serialized grade key examples |
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Read new grade keys |
| `frontend/packages/chassis/src/catalog/types.ts` | Update grades type |
| `tests/trading_analysis/test_result_serialization.py` | Update expected grade keys + fixture construction |
| `tests/trading_analysis/test_agent_snapshot.py` | Update expected grade keys + fixture construction |
| `tests/trading_analysis/test_date_filter.py` | Update grade field assertions |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Update timing expectation (1 symbol → N/A, not A), remove monkeypatch of `_calculate_overall_grade` (helper removed — GPA is inline) |
| `trading_analysis/interpretation_guide.md` | Update dimension names (Conviction→Edge, Position Sizing→Sizing, Averaging Down→Discipline) |
| `trading_analysis/README.md` | Update dimension names |

## Tests

**File:** `tests/trading_analysis/test_scorecard_v2.py` (new)

### Edge:
- All winners (avg +10%) → A for equity
- All losers (avg -5%) → F for equity
- Break-even → C
- Mixed: 12 equity (avg +3% → B) + 5 options (avg +25% → A) → GPA 3.29 → B
- Classes < 3 dropped, then total < 10 → N/A
- 12 total but 3 are fx_artifact → 9 gradeable → N/A
- All synthetic → N/A

### Discipline:
**Patience sub-score:**
- Ratio 2.0 → score 75 → A range
- Ratio 1.0 → score 50 → C range
- Ratio 0.33 → score ~10 → F range
- Zero-duration excluded, all zero → patience excluded
- No winners or losers → patience excluded

**Revenge trading sub-score:**
- 0 revenge trades → score 100
- 2 revenge out of 20 RTs (10%) → score 50
- Re-entry within 3 days of loss → revenge
- Re-entry after 4+ days → not revenge
- Re-entry after a win → not revenge
- < 5 round-trips → excluded
- Same-day re-entry (gap_days=0) after loss → revenge (tests .date() conversion)
- Overlapping timestamps same calendar day → gap_days=0, not negative

**Composite:**
- Both available: weighted 50/50
- Only patience available: patience alone
- No sub-scores → N/A
- < 5 round-trips → N/A

### Sizing:
- Positive correlation → A/B
- Negative correlation → D/F
- Near-zero → C
- Same size / same return → N/A
- < 15 → N/A
- Futures excluded

### Timing:
- Score 75%, 5 symbols → A
- Score 60%, 3 symbols → B
- Score 80%, 2 symbols → N/A (below minimum)
- Score 0, 0 symbols → N/A

### Integration:
- grades appears in agent snapshot with new keys
- grades appears in API response with new keys
- Overall = GPA of available dimensions
- Overall = N/A when < 2 dimensions
- Same analyzer run twice → _fifo_matcher_result resets, no stale data
- use_fifo=False → edge/sizing/discipline all N/A, timing may still grade, overall N/A (< 2 dimensions)

### CLI verification (main.py — not import-safe under pytest):
`results_to_dict()` and `generate_text_report()` are separate hand-built serializers that hard-code grade keys. They are not unit-testable (script-style imports fail under pytest). Verify manually:
```bash
python trading_analysis/main.py --json-only | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('grades',{}))"
python trading_analysis/main.py --text-report | grep -i "edge\|sizing\|discipline"
```

## Verification

1. `pytest tests/trading_analysis/test_scorecard_v2.py -v` — new tests pass
2. `pytest tests/trading_analysis/ -v` — all existing tests pass (with updated expected keys)
3. MCP: `get_trading_analysis(format="agent")` returns grades with new dimension names
4. Browser: Trading P&L card shows Edge, Sizing, Timing, Discipline
