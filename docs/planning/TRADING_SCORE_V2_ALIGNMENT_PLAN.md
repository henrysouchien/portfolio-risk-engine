# Trading Score V2 Alignment — Unify Per-Trade Grading Under V2 Methodology

> **Status**: PLAN v4 — addressing Codex round 3 findings (3 issues)
> **Created**: 2026-03-23
> **Depends on**: V2 scorecard (shipped `67be9af2`), timing shorts+all instruments (`9c6d1633`), sizing futures margin (`849ef5ba`)
> **Codex review**: R1 FAIL (5), R2 FAIL (5), R3 FAIL (3). This revision addresses all 13.

## Problem

Two independent scoring systems coexist:

1. **Legacy Win Score** — per-trade numeric score (-100 to +100) from three arbitrary step functions (return × 1.5, time efficiency buckets, risk management buckets). Maps to A+/A/B/C/D/F per trade. Shown on `TradingDetailCard.tsx` trade rows.

2. **V2 Scorecard** — portfolio-level grades (A-F) across four dimensions (Edge, Sizing, Timing, Discipline). Uses instrument-class thresholds, Spearman correlation, timing percentile, and behavioral metrics. Shown on `TradingPnLCard.tsx`.

The two systems use completely different methodologies, thresholds, and language. They can give contradictory signals.

## Goal

Replace the legacy per-trade Win Score with **per-trade grades derived from v2 methodology**, so both levels use the **same thresholds and language**. Per-trade grades will NOT mathematically roll up to portfolio-level grades (portfolio Edge uses class-level mean returns with sample guardrails, portfolio Timing uses multi-symbol average, etc.). The consistency is in shared language and thresholds, not arithmetic roll-up.

## Key Design Decision: Lot Rows Stay, Grouped by Round Trip

**Context** (Codex R2 finding #1): `TradeResult` rows are created per `ClosedTrade` lot, not per `RoundTrip`. A single AAPL position bought in 3 lots and sold produces 3 `TradeResult` rows but 1 `RoundTrip`.

**Decision**: Keep lot-level `TradeResult` rows (preserves tax-relevant cost basis detail). Add a `round_trip_id` to each `ClosedTrade`/`TradeResult` so all lots in the same round trip share the same ID and the same v2 grade.

**How it works**:
- `RoundTrip.from_lots()` generates a `round_trip_id` and stamps it on each constituent `ClosedTrade`
- When `TradeResult` is created from a `ClosedTrade`, it carries the `round_trip_id`
- V2 per-trade grades are computed per `RoundTrip`, then assigned to all `TradeResult` rows sharing that `round_trip_id`
- UI shows lot-level rows but with the round-trip-level grade (all 3 AAPL lots show the same grade)

## Prerequisite: Stable Round-Trip ID (Step 0)

**Collision-safe ID** (Codex R2 finding #2): Same-symbol same-day re-entries can collide with day-precision dates. Use a stronger key:

```python
# In RoundTrip.from_lots():
round_trip_id = f"{symbol}_{currency}_{direction}_{entry_date}_{exit_date}_{ordinal}"
```

Where `ordinal` is a per-(symbol, currency, direction, entry_date, exit_date) counter incremented during FIFO matching. This handles same-day re-entries. Alternatively, use `hashlib.md5(repr(sorted(lot_transaction_ids)))` for a content-addressed ID if transaction IDs are available on lots.

**ID ownership** (Codex R3 finding #3): Use content-addressed hash. `RoundTrip.from_lots()` is the single owner — it already has all constituent lots. No ordinal state needed in the matcher.

```python
# In RoundTrip.from_lots():
import hashlib
lot_keys = sorted(f"{lot.entry_date}_{lot.exit_date}_{lot.quantity}_{lot.entry_price}" for lot in lots)
round_trip_id = hashlib.md5(f"{symbol}_{currency}_{direction}_{'|'.join(lot_keys)}".encode()).hexdigest()[:12]
```

**Threading the ID through 5 sites**:

1. `ClosedTrade` — new `round_trip_id: str = ""` field. Set by `RoundTrip.from_lots()` which stamps all constituent lots after generating the ID.

2. `RoundTrip` — new `round_trip_id: str` field. Set in `from_lots()`.

3. `TradeResult` — new `round_trip_id: str` field. Populated from source `ClosedTrade.round_trip_id` at `analyzer.py` ~line 971 where `TradeResult` is constructed from `ClosedTrade`.

4. `TimingResult` — new `round_trip_id: str` field. Set at `analyzer.py` line 1261 inside the `for round_trip in grouped_round_trips` loop (each `TimingResult` is already created per round trip, not per symbol — the symbol grouping is just for batch price fetching). The `round_trip_id` from the `RoundTrip` object is directly available in the loop.
   - **Current code**: `analyze_timing()` returns `List[TimingResult]`. No change to return type needed.
   - **New lookup helper**: `_build_timing_lookup(timing_results) -> dict[str, TimingResult]` keyed by `round_trip_id`. Called once in `run_full_analysis()` after `analyze_timing()`.

5. `detect_revenge_trades()` — **dual return** (Codex R3 finding #2): Keep existing `List[Dict]` return for backward compat with `BehavioralAnalysis.revenge_trades` and its consumers at `analyzer.py` lines 370 and 1483. Add a second return value:
   ```python
   def detect_revenge_trades(round_trips: List[RoundTrip]) -> tuple[List[Dict[str, Any]], set[str]]:
       """Returns (revenge_events, revenge_round_trip_ids)."""
       # ... existing logic ...
       revenge_ids.add(current.round_trip_id)  # new: collect IDs
       return revenge_events, revenge_ids
   ```
   Callers updated: `compute_discipline_grade()` uses `revenge_events` (unchanged), `compute_per_trade_grades()` uses `revenge_ids` (new). `BehavioralAnalysis.revenge_trades` stays as `List[Dict]` — no new field needed since the set is only used internally during `run_full_analysis()`.

## Design

### Per-Trade V2 Grades — Two Dimensions + Revenge Flag

#### 1. Edge (per-trade)

**What it measures**: Did this trade make money, calibrated by instrument class?

**Logic**: Apply the same instrument-class thresholds from `compute_edge_grade()` to the round trip's `pnl_percent`:

| Class | A | B | C | D | F |
|-------|---|---|---|---|---|
| equity | ≥ 5% | ≥ 2% | ≥ 0% | ≥ -3% | < -3% |
| option | ≥ 20% | ≥ 8% | ≥ 0% | ≥ -10% | < -10% |
| futures | ≥ 8% | ≥ 3% | ≥ 0% | ≥ -5% | < -5% |

**Input**: `RoundTrip.pnl_percent` + `instrument_type` (mapped to class via existing `_INSTRUMENT_CLASS_MAP`).

**Always available**: Every non-synthetic, non-excluded round trip gets an Edge grade.

#### 2. Timing (per-trade)

**What it measures**: How close was the exit to the best available price during the holding period?

**Logic**: Look up this round trip's timing score from the timing results dict (keyed by `round_trip_id` after Step 0). Apply the same thresholds:

| Timing % | Grade |
|----------|-------|
| ≥ 70 | A |
| ≥ 55 | B |
| ≥ 40 | C |
| ≥ 25 | D |
| < 25 | F |

**N/A when**: Instrument type is excluded from timing (mutual_fund, fx, fx_artifact, income), or no price history available.

#### 3. Discipline — Revenge Flag Only (boolean, not graded)

**Codex R1 finding**: The 60/40 revenge+hold heuristic was arbitrary new behavior. Simplified to what v2 actually defines at the trade level.

**Logic**: `is_revenge: bool` — was this round trip flagged by `detect_revenge_trades()` (re-entry within 3 days of same-symbol loss)?

Not a separate letter grade. Instead, revenge status affects the composite:
- Revenge trades get a 1-grade penalty on the composite (e.g., Edge A + Timing B = B composite, but with revenge → C)
- This is simpler and more transparent than a weighted sub-score

#### 4. Sizing — Info Only, No Grade

- `size_percentile`: Position size rank among all round trips (0-100th percentile)
- Uses USD/margin-normalized capitals from existing sizing logic (respects FX via `fx_rate`, futures via `margin_rate * get_contract_spec()`)

### Per-Trade Composite Grade

```python
available = [edge, timing]  # only graded dimensions (not revenge, not sizing)
available = [g for g in available if g != "N/A"]

if len(available) >= 2:
    composite = _gpa_to_letter(mean([_GRADE_POINTS[g] for g in available]))
elif len(available) == 1:
    composite = "N/A"  # require ≥2 dimensions for a composite
else:
    composite = "N/A"

# Revenge penalty: drop composite by 1 letter grade
if is_revenge and composite != "N/A":
    composite = _drop_one_grade(composite)  # A→B, B→C, C→D, D→F, F→F
```

**N/A rule** (Codex R2 finding #3 — now consistent): Composite requires ≥2 available dimensions. No 1-dimension composites. This matches portfolio-level overall requiring ≥2.

### `use_fifo=False` Fallback

When `use_fifo=False`, `round_trips` is empty. All per-trade v2 grades are N/A, matching current behavior where v2 portfolio grades are all N/A in non-FIFO mode.

### What Gets Removed

1. `calculate_win_score()` in `metrics.py` — the three-component formula
2. `get_grade_from_score()` in `metrics.py` — score-to-letter mapping
3. `WinScoreComponents` dataclass in `metrics.py`
4. `Grade.from_score()` classmethod in `models.py`
5. `win_score: float` field on `TradeResult`
6. `avg_win_score: float` field on `FullAnalysisResult`
7. All serialization of `win_score` / `avg_win_score` in:
   - `TradeResult.to_dict()`
   - `FullAnalysisResult.to_api_response()` — including legacy grade distribution
   - `FullAnalysisResult.to_summary()`
   - `FullAnalysisResult.to_cli_report()`
   - `FullAnalysisResult.filter_by_date_range()` — `avg_win_score` recomputation
   - `main.py` — CLI JSON and text output
8. Sort-by-`win_score` in analyzer (replace with sort-by-`pnl_percent`)
9. **Prune** unused entries from `_GRADE_VERDICT` (A-/B+/B-/C+/C- never produced) — do NOT delete the map entirely, as `get_agent_snapshot()` still uses it for the `verdict` field (Codex R2 finding #5)

### What Gets Added

1. `round_trip_id: str` on `ClosedTrade`, `RoundTrip`, and `TradeResult`

2. `revenge_round_trip_ids: set[str]` on `BehavioralAnalysis` (alongside existing `revenge_trades: List[Dict]` for backward compat)

3. `compute_per_trade_grades()` function in `analyzer.py`:
   - Takes: list of `RoundTrip` objects, timing results dict (keyed by `round_trip_id`), revenge `round_trip_id` set, instrument class map, sizing capitals list (USD/margin-normalized with FX context from existing `_compute_sizing_capitals()`)
   - Returns: dict mapping `round_trip_id` → `PerTradeGrades`

4. `PerTradeGrades` dataclass in `models.py`:
   - `edge_grade: str`
   - `timing_grade: str` (N/A for excluded types)
   - `is_revenge: bool`
   - `composite_grade: str`
   - `size_percentile: float | None`

5. New fields on `TradeResult`:
   - `round_trip_id: str`
   - `grade: str` (v2 composite, replacing legacy Grade enum)
   - `edge_grade: str`
   - `timing_grade: str`
   - `is_revenge: bool`
   - `size_percentile: float | None`

6. `_drop_one_grade()` helper: A→B, B→C, C→D, D→F, F→F

## Implementation Steps

### Step 0: Add stable `round_trip_id` (~60 lines)

**Files**: `trading_analysis/fifo_matcher.py`, `trading_analysis/models.py`, `trading_analysis/analyzer.py`

a) `fifo_matcher.py`:
- Add `round_trip_id: str = ""` field to `ClosedTrade` dataclass
- Add `round_trip_id: str` field to `RoundTrip` dataclass
- In `RoundTrip.from_lots()`: generate content-addressed hash ID from lot keys, set `self.round_trip_id`, stamp on all constituent `ClosedTrade` objects via `lot.round_trip_id = self.round_trip_id`

b) `models.py`:
- Add `round_trip_id: str = ""` field to `TradeResult` dataclass
- Add `round_trip_id: str = ""` field to `TimingResult` dataclass

c) `analyzer.py`:
- At ~line 971 where `TradeResult` is constructed from `ClosedTrade`: copy `closed_trade.round_trip_id` to `TradeResult.round_trip_id`
- At ~line 1261 inside `analyze_timing()` per-round-trip loop: set `timing_result.round_trip_id = round_trip.round_trip_id` (the `RoundTrip` object is directly available in the loop variable)
- Add helper: `_build_timing_lookup(timing_results: List[TimingResult]) -> dict[str, TimingResult]` keyed by `round_trip_id`
- Update `detect_revenge_trades()` signature to return `tuple[List[Dict], set[str]]`. Add `revenge_ids.add(current.round_trip_id)` inside the revenge detection loop. Existing consumers (`compute_discipline_grade`, `BehavioralAnalysis`) use index [0] for the event list (unchanged). `compute_per_trade_grades()` uses index [1] for the ID set.

### Step 1: Add `compute_per_trade_grades()` (~60 lines)

**File**: `trading_analysis/analyzer.py`

- Iterates round trips by `round_trip_id`
- Computes edge grade from `pnl_percent` + instrument class using existing `_EDGE_THRESHOLDS`
- Looks up timing score from timing results dict by `round_trip_id`
- Checks revenge set membership by `round_trip_id`
- Computes size percentile using USD/margin-normalized capitals (reuse existing sizing capital logic with FX context)
- Produces composite grade (requires ≥2 dimensions, revenge drops 1 letter)
- Returns N/A for all grades when round_trips is empty (`use_fifo=False`)

### Step 2: Update `TradeResult` model

**File**: `trading_analysis/models.py`

- Add `round_trip_id`, `edge_grade`, `timing_grade`, `is_revenge`, `size_percentile` fields
- Remove `win_score: float`
- Replace `grade: Grade` → `grade: str` (v2 composite)
- Remove `Grade.from_score()` classmethod
- Update `to_dict()` serialization

### Step 3: Wire into `run_full_analysis()`

**File**: `trading_analysis/analyzer.py`

- Call `compute_per_trade_grades()` after timing analysis and revenge detection
- Build `round_trip_id` → `PerTradeGrades` lookup
- Assign per-trade grades to each `TradeResult` via matching `round_trip_id`
- Remove `calculate_win_score()` calls (FIFO path ~line 971, legacy path ~line 1079)
- Remove `avg_win_score` computation (~line 1513)
- Replace sort-by-`win_score` with sort-by-`pnl_percent`

### Step 4: Remove legacy scoring functions

**File**: `trading_analysis/metrics.py`

- Remove `calculate_win_score()`, `get_grade_from_score()`, `WinScoreComponents`
- Remove from `__init__.py` exports

### Step 5: Update all serialization

**Files**:
- `trading_analysis/models.py`:
  - `TradeResult.to_dict()` — v2 grades instead of win_score
  - `FullAnalysisResult.to_api_response()` — remove `avg_win_score`, remove legacy grade distribution
  - `FullAnalysisResult.to_summary()` — remove `avg_win_score`
  - `FullAnalysisResult.to_cli_report()` — remove `Avg Win Score` line, update per-trade scorecard table columns
  - `FullAnalysisResult.filter_by_date_range()` — remove `avg_win_score` recomputation
  - `get_agent_snapshot()` — include per-trade v2 grades in trade scorecard entries
  - `_GRADE_VERDICT` — prune unused A-/B+/B-/C+/C- entries, keep map for `verdict` field
- `trading_analysis/main.py`:
  - CLI JSON output — remove `avg_win_score`, update per-trade entries
  - CLI text output — remove `Avg Win Score`, update scorecard table columns

### Step 6: Update frontend types + display

**Files**:
- `frontend/packages/chassis/src/services/APIService.ts` — update `TradeScoreEntry`: remove `win_score`, add `edge_grade`, `timing_grade`, `is_revenge`, `size_percentile`
- `frontend/packages/chassis/src/catalog/types.ts` — remove `avg_win_score` from `trading_summary`, update `trade_scorecard[]` type
- `frontend/packages/connectors/src/resolver/registry.ts` — update mapping
- `frontend/packages/connectors/src/resolver/__tests__/portfolioScoping.test.ts` — update fixture
- `frontend/packages/ui/src/components/portfolio/performance/TradingDetailCard.tsx` — show v2 composite + Edge/Timing pills per trade row, revenge badge

### Step 7: Update tests (~12 files)

- Add `round_trip_id` to all `ClosedTrade`/`RoundTrip`/`TradeResult` fixtures across test files
- Update all `TradeResult` fixtures to remove `win_score=...` / `grade=Grade.X` and add v2 fields
- Add tests for `compute_per_trade_grades()`:
  - Equity trade with 6% return → Edge A
  - Option trade with -5% return → Edge C
  - Futures trade with 4% return → Edge B
  - Trade with timing score 80 → Timing A
  - Trade with no timing data (mutual fund) → Timing N/A
  - Revenge trade → is_revenge=True, composite dropped 1 grade
  - Non-revenge trade → is_revenge=False
  - Composite with Edge A + Timing C → B
  - Composite with Edge only (timing N/A, not revenge) → N/A (requires ≥2)
  - `use_fifo=False` → all N/A
  - Size percentile: largest trade = 100th, smallest = 0th
  - Futures sizing uses margin-adjusted capital
  - Same-symbol same-day re-entries get distinct `round_trip_id`s
  - Multiple lots in same round trip share same `round_trip_id` and grade
- Update revenge detection tests to verify dual return `(events, round_trip_ids_set)`
- Verify existing `compute_discipline_grade()` still works with `events[0]` indexing
- Update serialization tests (to_dict, to_api_response, to_summary, agent snapshot)
- Update date filter tests

### Step 8: Clean up dead code

- Prune unused entries from `_GRADE_VERDICT` (keep map, remove A-/B+/B-/C+/C-)
- Remove any remaining `win_score` / `avg_win_score` references
- Remove `WinScoreComponents` imports
- Remove `Grade.from_score()`

## Verification

- All existing v2 scorecard tests pass (portfolio-level grades unchanged)
- Per-trade grades use the same thresholds as portfolio-level (shared language, not arithmetic roll-up)
- No `win_score` or `avg_win_score` references remain in codebase (grep verification)
- `round_trip_id` is stable, collision-safe, and unique across same-symbol same-day re-entries
- All lots in a round trip share the same `round_trip_id` and grade
- Frontend displays v2 per-trade grades on trade rows
- Agent snapshot includes per-trade grade breakdown
- CLI output uses v2 grades
- `use_fifo=False` produces all-N/A per-trade grades
- `_GRADE_VERDICT` still works for `get_agent_snapshot()` verdict field
- `BehavioralAnalysis.revenge_trades` backward compat preserved

## Risk Assessment

**Low risk**: Portfolio-level v2 grading is completely untouched. Only per-trade scoring changes.

**Step 0 risk**: Adding `round_trip_id` touches `fifo_matcher.py` (critical path). The ID is additive (new field, no existing field changes). Timing result re-keying changes dict key from symbol to `round_trip_id` — all consumers of timing results must be updated.

**Migration safety**: `grade` field on `TradeResult` changes type from `Grade` enum to `str`. All v2 consumers already handle string grades. Removal of `win_score` from API responses is breaking for any external consumer — but frontend never displays it, and agent snapshot already excludes it.

## Codex Review Resolution Tracker

### Round 1 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | No stable round-trip ID | Step 0: `round_trip_id` threaded through ClosedTrade, RoundTrip, TradeResult, TimingResult, revenge detection |
| 2 | High | Roll-up consistency overclaimed | Reframed: "shared thresholds/language, not arithmetic roll-up" |
| 3 | Medium | N/A rules inconsistent | Composite requires ≥2 dimensions. No 1-dimension composites. |
| 4 | Medium | Migration surface understated | Steps 5-7 expanded with all serializers, `filter_by_date_range()`, CLI, frontend fixtures |
| 5 | Medium | `use_fifo=False` and sizing FX context | Explicit all-N/A fallback. Sizing uses existing USD/margin capital logic with FX. |

### Round 2 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | TradeResult is lot-based, not round-trip-based | Design decision: keep lot rows, add `round_trip_id` to `ClosedTrade` → `TradeResult`. Grades assigned from round trip, shared by all lots. |
| 2 | High | round_trip_id collisions on same-day re-entries | Content-addressed hash from lot keys in `RoundTrip.from_lots()`. Single owner, no ordinal state. |
| 3 | Medium | Composite N/A rule self-contradictory | Fixed: ≥2 required, no 1-dimension fallback. Pseudocode and text now agree. |
| 4 | Medium | Revenge migration incomplete — BehavioralAnalysis not updated | `detect_revenge_trades()` returns `tuple[List[Dict], set[str]]`. Existing consumers use [0], per-trade grades use [1]. No BehavioralAnalysis changes needed. |
| 5 | Medium | `_GRADE_VERDICT` still used by get_agent_snapshot() | Changed from "remove" to "prune unused entries" — keep map, remove only A-/B+/B-/C+/C- variants. |

### Round 3 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | — | Timing lookup underspecified — `TimingResult` has no `round_trip_id`, `analyze_timing()` returns `List[TimingResult]` | `TimingResult` gets `round_trip_id` field, set inside the per-round-trip loop at analyzer.py line 1261 (RoundTrip object is directly available). `_build_timing_lookup()` helper creates `dict[str, TimingResult]`. Return type of `analyze_timing()` unchanged. |
| 2 | — | `detect_revenge_trades()` contract split unresolved | Dual return: `tuple[List[Dict], set[str]]`. Existing consumers use index [0] (unchanged). Per-trade grades use index [1]. No new BehavioralAnalysis field needed — ID set is used only internally in `run_full_analysis()`. |
| 3 | — | round_trip_id ownership ambiguous (from_lots vs matcher) | Single owner: `RoundTrip.from_lots()` generates content-addressed hash from lot keys. No matcher state needed. |
