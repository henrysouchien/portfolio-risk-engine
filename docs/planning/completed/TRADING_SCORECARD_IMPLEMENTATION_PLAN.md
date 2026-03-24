# Trading Scorecard v2 — Implementation Plan

## Overview

Implement the 4-dimension scoring model from `TRADING_SCORECARD_REDESIGN.md`. This plan covers the concrete code changes, field-by-field data flow, and phased rollout.

## Phase 1: Round-Trip Aggregation + Edge + Discipline

These three have no data model gaps — they can be built on existing fields.

### Step 1.1: RoundTrip dataclass

**File:** `trading_analysis/models.py`

```python
@dataclass
class RoundTrip:
    symbol: str
    currency: str
    direction: str  # 'LONG' / 'SHORT'
    instrument_type: str  # 'equity', 'option', 'futures', etc.

    # Aggregated from lots
    entry_date: datetime        # earliest lot entry
    exit_date: datetime         # latest lot exit
    days_in_trade: int          # exit_date - entry_date
    num_lots: int               # how many FIFO lots comprise this round-trip
    cost_basis: float           # sum of lot cost_basis (local currency)
    cost_basis_usd: float       # sum of lot cost_basis × fx_rate
    proceeds: float             # sum of lot proceeds (local currency)
    pnl_dollars: float          # sum of lot pnl_dollars (local currency)
    pnl_dollars_usd: float      # sum of lot pnl_dollars_usd
    pnl_percent: float          # pnl_dollars_usd / cost_basis_usd * 100
    is_winner: bool             # pnl_dollars_usd > 0
```

### Step 1.2: aggregate_to_round_trips()

**File:** `trading_analysis/analyzer.py`

**Inputs:** `closed_trades: list[ClosedTrade]`, `open_lots: dict[tuple, list[OpenLot]]`, `fx_rates: dict[str, float]`

**Algorithm:**
1. Group closed_trades by `(symbol, currency, direction)` — same key as FIFO matcher
2. Within each group, sort by `exit_date`
3. Walk through lots chronologically. Accumulate into current round-trip.
4. After each lot, check: does `open_lots[(symbol, currency, direction)]` have remaining quantity?
   - If YES: round-trip still open, keep accumulating
   - If NO and this was the last exit: round-trip complete, emit it and start a new one
5. **Simplification for v1:** Since we only have the final matcher state (not per-lot intermediate state), use a heuristic: a round-trip ends when there's a gap > 1 day between the last exit_date of accumulated lots and the next entry_date. If all lots for a key are in `closed_trades` and NOT in `open_lots`, the entire batch is one completed round-trip. This covers 90%+ of cases.

**Edge case — still-open positions:** If `open_lots` has remaining quantity for a key, exclude that key's lots from scoring entirely (incomplete round-trip, can't grade yet).

**Output:** `list[RoundTrip]`

### Step 1.3: compute_edge_grade()

**File:** `trading_analysis/analyzer.py`

**Input:** `round_trips: list[RoundTrip]`

**Logic:**
1. Filter to completed round-trips only
2. If < 10 round-trips → return N/A
3. Group by instrument_type class: equity (equity, mutual_fund, bond, unknown), option, futures
4. Per class: compute simple average of `pnl_percent` across round-trips
5. Map to grade using instrument-specific thresholds (from design doc)
6. If mixed portfolio: weight per-class grades by round-trip count → overall Edge grade

### Step 1.4: compute_discipline_grade()

**File:** `trading_analysis/analyzer.py`

**Input:** `round_trips: list[RoundTrip]`

**Logic:**
1. Split into winners (`is_winner=True`) and losers
2. If fewer than 5 round-trips with both wins AND losses → return N/A
3. Compute median hold duration for winners and losers separately
4. Handle zero-duration: if median is 0 days, use 0.5 (half a day) as floor
5. Patience ratio = median_winner_hold / median_loser_hold
6. Score = 50 + 36 × ln(clamp(ratio, 0.2, 5.0))
7. Map score to grade (A ≥ 75, B ≥ 55, C ≥ 35, D ≥ 20, F < 20)

### Step 1.5: Integrate into FullAnalysisResult

**File:** `trading_analysis/models.py`

- Add `round_trips: list[RoundTrip]` field to FullAnalysisResult
- Add `grades_v2: dict` field alongside existing `grades`
- In `get_agent_snapshot()`: emit `grades_v2` alongside existing grades
- In `to_api_response()`: emit `grades_v2` alongside existing grades
- In `to_summary()`: emit `grades_v2` alongside existing grades

Dual-write: old grades untouched, new grades added under `grades_v2` key.

### Step 1.6: Wire up in analyzer

**File:** `trading_analysis/analyzer.py`

In `TradingAnalyzer.analyze()` (or wherever FullAnalysisResult is assembled):
1. After FIFO matching + TradeResult creation, call `aggregate_to_round_trips()`
2. Call `compute_edge_grade()` and `compute_discipline_grade()`
3. Compute overall_v2 GPA from available grades
4. Store in FullAnalysisResult.grades_v2

## Phase 2: Sizing Grade

Requires USD cost basis on round-trips — slight data plumbing.

### Step 2.1: Add cost_basis_usd to TradeResult

**File:** `trading_analysis/analyzer.py` (lines 691-694, where FX conversion happens)

Currently only `pnl_dollars_usd` is computed. Add:
```python
for trade_result in trade_results:
    currency = (trade_result.currency or "USD").upper()
    rate = fx_rates.get(currency, 1.0)
    trade_result.pnl_dollars_usd = trade_result.pnl_dollars * rate
    trade_result.cost_basis_usd = trade_result.cost_basis * rate  # NEW
```

Add `cost_basis_usd: float = 0.0` field to TradeResult dataclass.

### Step 2.2: Propagate to RoundTrip

In `aggregate_to_round_trips()`, sum `cost_basis_usd` across lots in the round-trip. Already planned in the RoundTrip dataclass.

### Step 2.3: compute_sizing_grade()

**File:** `trading_analysis/analyzer.py`

**Input:** `round_trips: list[RoundTrip]`

**Logic:**
1. If < 15 round-trips → return N/A
2. Extract pairs: (cost_basis_usd, pnl_percent) per round-trip
3. Check for sufficient variation: ≥ 4 distinct cost_basis_usd ranks (after tie-collapsing). If not → N/A
4. Compute Spearman rank correlation using `scipy.stats.spearmanr` (already a dependency) or manual rank computation
5. Map correlation to grade (A ≥ 0.25, B ≥ 0.10, C ≥ -0.05, D ≥ -0.20, F < -0.20)
6. Add confidence qualifier: "moderate" at 15-19 round-trips, "high" at 20+

**Dependency check:** Verify scipy is available. If not, implement manual Spearman (rank both arrays, compute Pearson on ranks — ~10 lines).

### Step 2.4: Integrate into grades_v2

Same pattern as Phase 1 — add sizing to the grades_v2 dict.

## Phase 3: Frontend + Flags

### Step 3.1: Frontend types

**File:** `frontend/packages/chassis/src/catalog/types.ts`

Add to TradingAnalysisSourceData grades type:
```typescript
grades?: {
    // v1 (existing)
    overall?: string;
    conviction?: string;
    timing?: string;
    position_sizing?: string;
    averaging_down?: string;
    // v2 (new)
    overall_v2?: string;
    edge?: string;
    sizing?: string;
    discipline?: string;
}
```

### Step 3.2: TradingPnLCard reads v2

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

Update `subGrades` array to read v2 keys with v1 fallback:
```typescript
const subGrades = [
    {
        label: 'Edge',
        description: 'Trade selection quality',
        tooltip: 'Are you picking good trades? Size-neutral average return.',
        value: tradingSummaryData?.grades?.edge?.trim()
            || tradingSummaryData?.grades?.conviction?.trim()  // v1 fallback
            || 'N/A',
    },
    // ... sizing, timing, discipline
]
```

### Step 3.3: Update trading flags

**File:** `core/trading_flags.py`

Add v2-aware flags that read from the new snapshot structure. Keep existing v1 flags working (they read from the same snapshot, just different keys).

## Phase 4 (Future): Futures Margin

Out of scope for initial implementation. Futures use notional cost basis (qty × price) for sizing ranks — directionally correct for ranking but not precise capital-at-risk.

To add later:
- Add margin_rate lookup per contract (from IBKR or config)
- Compute capital_at_risk = notional × margin_rate
- Use capital_at_risk instead of cost_basis for futures sizing ranks

## Files Changed (All Phases)

| File | Phase | Change |
|------|-------|--------|
| `trading_analysis/models.py` | 1 | RoundTrip dataclass, grades_v2 in FullAnalysisResult, dual-write in all emission paths |
| `trading_analysis/analyzer.py` | 1+2 | aggregate_to_round_trips(), compute_edge_grade(), compute_discipline_grade(), compute_sizing_grade(), cost_basis_usd |
| `trading_analysis/main.py` | 1 | Update text report for v2 grades |
| `core/trading_flags.py` | 3 | v2-aware flags |
| `trading_analysis/interpretation_guide.md` | 3 | v2 metric interpretations |
| `frontend/packages/chassis/src/catalog/types.ts` | 3 | v2 grade keys |
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | 3 | Read v2 keys, update labels/tooltips |
| `tests/trading_analysis/test_analyzer.py` | 1+2 | Round-trip aggregation + scoring tests |
| `tests/trading_analysis/test_result_serialization.py` | 1 | Assert v2 keys in API response |
| `tests/trading_analysis/test_agent_snapshot.py` | 1 | Assert v2 keys in snapshot |
| `tests/core/test_trading_flags.py` | 3 | v2 flag tests |

## Test Plan

### Phase 1 Tests:
- Round-trip aggregation: single symbol (3 lots → 1 round-trip), multi-symbol, scaled-in position, position that goes flat then re-enters
- Edge grade: all winners → A, all losers → F, break-even → C, mixed equity+options with instrument-aware thresholds
- Discipline: winners held longer → A, losers held longer → F, equal → C, no winners → N/A

### Phase 2 Tests:
- Sizing grade: positive correlation → A/B, negative → D/F, no variation → N/A, < 15 round-trips → N/A
- USD cost basis: multi-currency portfolio, FX rate applied correctly

### Phase 3 Tests:
- Frontend reads v2 keys when available, falls back to v1
- Flags reference new dimension names

## Verification

1. `pytest tests/trading_analysis/ -v` — all existing + new tests pass
2. `pytest tests/core/test_trading_flags.py -v` — flag tests pass
3. TypeScript check for frontend changes
4. Browser: Performance → Trading P&L card shows new dimension labels (Edge, Sizing, Timing, Discipline)
5. MCP: `get_trading_analysis` returns both v1 and v2 grades in response
