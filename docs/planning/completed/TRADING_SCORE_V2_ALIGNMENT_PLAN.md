# Trading Score V2 Alignment — Unify Per-Trade Grading Under V2 Methodology

> **Status**: PLAN v11 — addressing Codex round 10 findings (1 issue)
> **Created**: 2026-03-23
> **Depends on**: V2 scorecard (shipped `67be9af2`), timing shorts+all instruments (`9c6d1633`), sizing futures margin (`849ef5ba`)
> **Codex review**: R1 FAIL (5), R2 FAIL (5), R3 FAIL (3), R4 FAIL (4), R5 FAIL (2), R6 FAIL (6), R7 FAIL (3), R8 FAIL (4), R9 FAIL (1), R10 FAIL (1). This revision addresses all 34.

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

**Stable ID** (Codex R2 finding #2): Same-symbol same-day re-entries can collide with day-precision dates. Use a content-addressed key:

```python
# In RoundTrip.from_lots():
round_trip_id = f"{symbol}_{currency}_{direction}_{entry_date}_{exit_date}_{ordinal}"
```

Where `ordinal` is a per-(symbol, currency, direction, entry_date, exit_date) counter incremented during FIFO matching. This handles same-day re-entries. Alternatively, use `hashlib.md5(repr(sorted(lot_transaction_ids)))` for a content-addressed ID if transaction IDs are available on lots.

**ID ownership** (Codex R3 finding #3): Use content-addressed hash. `RoundTrip.from_lots()` is the single owner — it already has all constituent lots. No ordinal state needed in the matcher.

```python
# In RoundTrip.from_lots():
import hashlib

def _lot_key(lot: ClosedTrade) -> str:
    """Build a key per lot. Falls back to price/qty/dates when transaction IDs are None."""
    entry_id = lot.entry_transaction_id or f"{lot.entry_date}_{lot.entry_price}"
    exit_id = lot.exit_transaction_id or f"{lot.exit_date}_{lot.exit_price}"
    return f"{entry_id}_{exit_id}_{lot.quantity}"

# ClosedTrade fields: entry_price/exit_price (fifo_matcher.py:81,86),
# entry_transaction_id/exit_transaction_id are Optional[str] (fifo_matcher.py:103-104).
# Some normalizers (e.g., ibkr_statement) may emit None transaction_ids for certain row types.
# Fallback uses price/date/qty — best-effort uniqueness, not guaranteed collision-free.
lot_keys = sorted(_lot_key(lot) for lot in lots)
round_trip_id = hashlib.md5(
    f"{symbol}_{currency}_{direction}_{'|'.join(lot_keys)}".encode()
).hexdigest()[:12]
```

**Threading the ID through 5 sites**:

1. `ClosedTrade` — new `round_trip_id: str = ""` field. Set by `RoundTrip.from_lots()` which stamps all constituent lots after generating the ID.

2. `RoundTrip` — new `round_trip_id: str` field. Set in `from_lots()`.

3. `TradeResult` — new `round_trip_id: str` field. Populated from source `ClosedTrade.round_trip_id` at `analyzer.py` ~line 1044 where `TradeResult` is constructed from `ClosedTrade`.

4. `TimingResult` — new `round_trip_id: str` field. Set at `analyzer.py` ~line 1327 inside the `for round_trip in grouped_round_trips` loop (each `TimingResult` is already created per round trip, not per symbol — the symbol grouping is just for batch price fetching). The `round_trip_id` from the `RoundTrip` object is directly available in the loop.
   - **Current code**: `analyze_timing()` returns `List[TimingResult]`. No change to return type needed.
   - **New lookup helper**: `_build_timing_lookup(timing_results) -> dict[str, TimingResult]` keyed by `round_trip_id`. Called once in `run_full_analysis()` after `analyze_timing()`.

5. `detect_revenge_trades()` — **dual return** (Codex R3 finding #2): Change return type from `List[Dict]` to `tuple[List[Dict], set[str]]`:
   ```python
   def detect_revenge_trades(round_trips: List[RoundTrip]) -> tuple[List[Dict[str, Any]], set[str]]:
       """Returns (revenge_events, revenge_round_trip_ids)."""
       # ... existing logic ...
       revenge_ids.add(current.round_trip_id)  # new: collect IDs
       return revenge_events, revenge_ids
   ```
   **Three call sites** (all in `analyzer.py`):
   - `compute_discipline_grade()` at line 434 (standalone function): destructure as `revenge_events, _ = detect_revenge_trades(non_synthetic)`. Only uses `revenge_events` for rate calculation. Does NOT need `revenge_ids`.
   - `analyze_behavior()` at line 1549 (method on `TradingAnalyzer`): destructure as `revenge_events, _ = detect_revenge_trades(non_synthetic_round_trips)`. Passes `revenge_events` to `BehavioralAnalysis.revenge_trades` (unchanged).
   - `run_full_analysis()` at line 1625 (method on `TradingAnalyzer`): calls `self.analyze_behavior()` which returns `BehavioralAnalysis` — does NOT call `detect_revenge_trades()` directly. To get `revenge_ids` for `compute_per_trade_grades()`, add a **separate** call: `_, revenge_ids = detect_revenge_trades(non_synthetic_round_trips)` in `run_full_analysis()` after `analyze_behavior()`.

   `BehavioralAnalysis.revenge_trades` stays as `List[Dict]`.

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

**Input**: `RoundTrip.pnl_percent` + `instrument_type` (mapped to class via existing `_edge_instrument_class()`).

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

### Partial Round Trips (Position Still Open)

When a position is partially closed but still open, `ClosedTrade` objects are appended to `closed_trades` and `_current_round_trip_lots`, but `_close_round_trip()` is NOT called (it only fires when `open_lots[lot_key]` is empty, i.e., position goes flat — see `fifo_matcher.py:842-843`). These `ClosedTrade` objects have no finalized `RoundTrip`, so their `round_trip_id` remains `""`.

**Handling**: `TradeResult` rows with `round_trip_id=""` get all-N/A grades (same as `use_fifo=False`). The grade assignment loop in Step 3 skips them — only `TradeResult` rows with a non-empty `round_trip_id` that matches an entry in the `PerTradeGrades` lookup get graded.

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
   - `FullAnalysisResult.to_api_response()` — remove `avg_win_score` from summary
   - `FullAnalysisResult.to_summary()`
   - `FullAnalysisResult.to_cli_report()`
   - `FullAnalysisResult.filter_by_date_range()` — `avg_win_score` recomputation
   - `main.py` — CLI JSON and text output
8. Sort-by-`win_score` in analyzer (replace with sort-by-`pnl_percent`)
9. **Prune** unused entries from `_GRADE_VERDICT` (A-/B+/B-/C+/C- never produced) — do NOT delete the map entirely, as `get_agent_snapshot()` still uses it for the `verdict` field (Codex R2 finding #5)

### What Gets Added

1. `round_trip_id: str` on `ClosedTrade`, `RoundTrip`, and `TradeResult`

2. `compute_per_trade_grades()` function in `analyzer.py`:
   - Takes: list of `RoundTrip` objects, timing results dict (keyed by `round_trip_id`), revenge `round_trip_id` set, instrument class map, sizing capitals list (USD/margin-normalized with FX context from existing `_get_sizing_capital()`)
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
- At ~line 1044 where `TradeResult` is constructed from `ClosedTrade`: copy `closed_trade.round_trip_id` to `TradeResult.round_trip_id`
- At ~line 1327 inside `analyze_timing()` per-round-trip loop: set `timing_result.round_trip_id = round_trip.round_trip_id` (the `RoundTrip` object is directly available in the loop variable)
- Add helper: `_build_timing_lookup(timing_results: List[TimingResult]) -> dict[str, TimingResult]` keyed by `round_trip_id`
- Update `detect_revenge_trades()` signature to return `tuple[List[Dict], set[str]]`. Add `revenge_ids.add(current.round_trip_id)` inside the revenge detection loop.
- Update all three callers to destructure:
  - `compute_discipline_grade()` (line 434): `revenge_events, _ = detect_revenge_trades(non_synthetic)` — only uses events for rate calc
  - `analyze_behavior()` (line 1549): `revenge_events, _ = detect_revenge_trades(non_synthetic_round_trips)` — passes events to `BehavioralAnalysis.revenge_trades`
  - `run_full_analysis()` (line 1625+): add new call `_, revenge_ids = detect_revenge_trades(non_synthetic_round_trips)` after `self.analyze_behavior()` — passes `revenge_ids` to `compute_per_trade_grades()`
- Add regression test: `BehavioralAnalysis.revenge_trades` still receives the event list after dual-return change
- Add regression test: `compute_discipline_grade()` still produces correct grades after dual-return change

### Step 1: Add `compute_per_trade_grades()` (~60 lines)

**File**: `trading_analysis/analyzer.py`

- Iterates round trips by `round_trip_id`
- **Exclusion filter**: Skip synthetic round trips and cash-equivalent symbols (matching portfolio-level v2 exclusions at `analyzer.py` ~lines 198, 416, 1271). Excluded round trips get all-N/A grades.
- Computes edge grade from `pnl_percent` + instrument class using existing `_EDGE_GRADE_THRESHOLDS`
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

**FIFO path** (~line 1020+):
- In `_analyze_trades_fifo()` where `TradeResult` is constructed from `ClosedTrade` (~line 1044): construct with default v2 fields (`grade="N/A"`, `edge_grade="N/A"`, `timing_grade="N/A"`, `is_revenge=False`, `size_percentile=None`, `round_trip_id=closed_trade.round_trip_id`)
- Remove `calculate_win_score()` calls at that same construction site
- Later in `run_full_analysis()`, after timing analysis and revenge detection: call `compute_per_trade_grades()`, build `round_trip_id` → `PerTradeGrades` lookup, then overwrite the default v2 fields on each `TradeResult` via matching `round_trip_id`

**Averaged path** (~line 1080+, `use_fifo=False`):
- `TradeResult`s are created directly (no `RoundTrip`, no `ClosedTrade`)
- Initialize all per-trade v2 fields to defaults: `grade="N/A"`, `edge_grade="N/A"`, `timing_grade="N/A"`, `is_revenge=False`, `size_percentile=None`, `round_trip_id=""`
- Remove `calculate_win_score()` calls (~line 1150)

**Sort replacement** (two sites):
- At ~line 1076 (FIFO path return): replace `sorted(..., key=lambda x: x.win_score, reverse=True)` with sort-by-`pnl_percent`
- At ~line 1182 (averaged path return): same replacement

**Common** (~line 1565+):
- Remove `avg_win_score` computation

### Step 4: Remove legacy scoring functions

**File**: `trading_analysis/metrics.py`

- Remove `calculate_win_score()`, `get_grade_from_score()`, `WinScoreComponents`
- Remove from `__init__.py` exports

### Step 5: Update all serialization

**Files**:
- `trading_analysis/models.py`:
  - `TradeResult.to_dict()` — v2 grades instead of win_score
  - `FullAnalysisResult.to_api_response()` — remove `avg_win_score` from `summary` dict
  - `FullAnalysisResult.to_summary()` — remove `avg_win_score`
  - `FullAnalysisResult.to_cli_report()` — no scorecard table here (just winners/losers); remove any `win_score` references if present
  - `FullAnalysisResult.filter_by_date_range()` — remove `avg_win_score` recomputation
  - `get_agent_snapshot()` — per-trade grades already excluded from snapshot (snapshot uses portfolio-level v2 grades only). No changes needed here.
  - `_GRADE_VERDICT` — prune unused A-/B+/B-/C+/C- entries, keep map for `verdict` field
- `trading_analysis/main.py`:
  - CLI JSON output — remove `avg_win_score`, update per-trade entries
  - CLI text output — remove `Avg Win Score` line, update per-trade scorecard table columns (the scorecard table lives in `main.py`, not `to_cli_report()`)

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
  - Lots with `None` transaction IDs fall back to price/date keys and still produce stable IDs
  - Synthetic round trips get all-N/A grades (excluded from per-trade grading)
  - Cash-equivalent round trips get all-N/A grades (excluded from per-trade grading)
  - Partially-closed positions (still open, `round_trip_id=""`) get all-N/A grades
- Update revenge detection tests to verify dual return `(events, round_trip_ids_set)`
- Verify `compute_discipline_grade()` still produces correct grades after dual-return destructuring
- Verify `BehavioralAnalysis.revenge_trades` still receives the event list
- Update serialization tests (to_dict, to_api_response, to_summary, agent snapshot)
- Update date filter tests
- Add tests for `results_to_dict()` and `generate_text_report()` in `trading_analysis/main.py` (verify `win_score`/`avg_win_score` removed, v2 fields present)
- Add `TradingDetailCard` frontend tests: composite/edge/timing pill rendering, revenge badge display, N/A handling
- Add resolver assertions for new mapped fields in `portfolioScoping.test.ts`

### Step 8: Clean up dead code

- Prune unused entries from `_GRADE_VERDICT` (keep map, remove A-/B+/B-/C+/C-)
- Remove any remaining `win_score` / `avg_win_score` references in runtime/backend/frontend sources
- Remove `WinScoreComponents` imports
- Remove `Grade.from_score()`
- Update `trading_analysis/examples/usage_example.py` — remove `win_score` references
- Update `trading_analysis/README.md` — remove legacy scoring documentation

## Verification

- All existing v2 scorecard tests pass (portfolio-level grades unchanged)
- Per-trade grades use the same thresholds as portfolio-level (shared language, not arithmetic roll-up)
- No `win_score` or `avg_win_score` references remain in runtime/backend/frontend sources (grep verification; `examples/usage_example.py` and `README.md` also updated)
- `round_trip_id` is stable and content-addressed; collision-free when transaction IDs are present, best-effort when they are None
- All lots in a round trip share the same `round_trip_id` and grade
- Frontend displays v2 per-trade grades on trade rows
- Agent snapshot remains portfolio-level only; no per-trade grade breakdown is added to `get_agent_snapshot()`
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
| 1 | — | Timing lookup underspecified — `TimingResult` has no `round_trip_id`, `analyze_timing()` returns `List[TimingResult]` | `TimingResult` gets `round_trip_id` field, set inside the per-round-trip loop at analyzer.py ~line 1327 (RoundTrip object is directly available). `_build_timing_lookup()` helper creates `dict[str, TimingResult]`. Return type of `analyze_timing()` unchanged. |
| 2 | — | `detect_revenge_trades()` contract split unresolved | Dual return: `tuple[List[Dict], set[str]]`. Existing consumers use index [0] (unchanged). Per-trade grades use index [1]. No new BehavioralAnalysis field needed — ID set is used only internally in `run_full_analysis()`. |
| 3 | — | round_trip_id ownership ambiguous (from_lots vs matcher) | Single owner: `RoundTrip.from_lots()` generates content-addressed hash from lot keys. No matcher state needed. |

### Round 4 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Hash uses dates/qty/price, not transaction IDs — collisions possible | Fixed: hash now uses `entry_transaction_id` + `exit_transaction_id` from `ClosedTrade` (available at `fifo_matcher.py:103-104`) |
| 2 | Medium | Revenge contract contradictory — plan adds field to BehavioralAnalysis in one place, says "no change needed" in another | Fixed: removed stale `revenge_round_trip_ids` on BehavioralAnalysis. ID set is internal to `run_full_analysis()` only. |
| 3 | Medium | `use_fifo=False` averaged path creates TradeResults with no round trips — needs explicit N/A initialization | Fixed: Step 3 now has explicit averaged-path section initializing all v2 fields to defaults |
| 4 | Medium | Source mismatches — `_INSTRUMENT_CLASS_MAP` (doesn't exist), `_compute_sizing_capitals()` (doesn't exist), grade distribution claim, trade scorecard entries claim | Fixed: corrected to `_edge_instrument_class()`, `_get_sizing_capital()`. Removed incorrect grade distribution and trade scorecard claims from serialization steps. |

### Round 5 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Edge threshold constant named `_EDGE_THRESHOLDS` in plan but `_EDGE_GRADE_THRESHOLDS` in source | Fixed: all references updated to `_EDGE_GRADE_THRESHOLDS` |
| 2 | Low | Analyzer line numbers stale (~971, ~1261, ~370/1483, ~951/1012/1513) | Fixed: updated to current source locations (~1044, ~1327, ~434/1549, ~1020/1080/1549) |

### Round 6 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Verification says "Agent snapshot includes per-trade grade breakdown" but Step 5 says no changes | Fixed: Verification now says "Agent snapshot remains portfolio-level only; no per-trade grade breakdown is added" |
| 2 | High | FIFO path doesn't specify default v2 fields during `TradeResult` construction before later mutation | Fixed: Step 3 FIFO path now explicitly constructs `TradeResult` with default v2 fields, then overwrites after `compute_per_trade_grades()` |
| 3 | Medium | Stale line refs remain in Round 3/4 tracker entries and Step 3 Common section | Fixed: R3#1 → `~line 1327`, R4#1 → `fifo_matcher.py:103-104`, Common → `~line 1565+` |
| 4 | Medium | Test plan missing `main.py` serializer tests and frontend `TradingDetailCard` rendering tests | Fixed: added `results_to_dict()`/`generate_text_report()` tests, TradingDetailCard pill/badge tests, resolver assertions |
| 5 | Medium | Cleanup scope misses `examples/usage_example.py` and `README.md` which reference `win_score` | Fixed: added both to Step 8 cleanup. Verification claim scoped to runtime/backend/frontend + those two files |
| 6 | Low | `to_api_response()` described as having "legacy grade distribution" but it doesn't | Fixed: changed to "remove `avg_win_score` from summary" |

### Round 7 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | `ClosedTrade.entry_transaction_id` is `Optional[str]` — some normalizers emit `None`. Content-addressed hash overclaims collision safety. | Fixed: `_lot_key()` helper falls back to `entry_date_price`/`exit_date_price` when transaction IDs are None. Added test case for None-ID lots. |
| 2 | Medium | Sort-by-`win_score` at analyzer.py ~lines 1076 and 1182, not in Common section at ~1565 | Fixed: separated "Sort replacement" section with both line sites. Common section now only covers `avg_win_score` removal. |
| 3 | Medium | Scorecard table is in `main.py`, not `to_cli_report()` — plan attributed it to wrong method | Fixed: `to_cli_report()` description corrected (just winners/losers). Scorecard table update moved to `main.py` section. |

### Round 8 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | `_lot_key()` used `lot.avg_entry_price`/`lot.avg_exit_price` but `ClosedTrade` has `entry_price`/`exit_price` | Fixed: corrected to `lot.entry_price`/`lot.exit_price` (fifo_matcher.py:81,86) |
| 2 | Medium | Plan overclaims "collision-safe" and "unique" for fallback hash when transaction IDs are None | Fixed: tempered to "stable and content-addressed; collision-free when transaction IDs present, best-effort when None" |
| 3 | Medium | Revenge dual-return callers are `analyze_behavior()` and `run_full_analysis()`, not `compute_discipline_grade` and `BehavioralAnalysis` | Fixed: explicit caller update instructions for both sites with destructuring. Added regression test for `BehavioralAnalysis.revenge_trades`. |
| 4 | Medium | Per-trade grading doesn't exclude synthetic and cash-equivalent round trips (portfolio v2 does at ~lines 198, 416, 1271) | Fixed: added exclusion filter in Step 1 + test cases for synthetic/cash-equivalent → all-N/A |

### Round 9 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Revenge dual-return call sites still wrong — 3 call sites: `compute_discipline_grade()` (line 434), `analyze_behavior()` (line 1549), `run_full_analysis()` (line 1625, indirect). Plan confused which function was at which line. `compute_discipline_grade()` calls `detect_revenge_trades()` internally. | Fixed: all 3 call sites identified with correct line numbers and correct function names. `run_full_analysis()` gets a separate `_, revenge_ids = detect_revenge_trades()` call since it doesn't call `detect_revenge_trades()` directly. |

### Round 10 Findings
| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Partially-closed positions produce `ClosedTrade` objects with no finalized `RoundTrip` — `round_trip_id` stays empty, no grading path defined | Fixed: added "Partial Round Trips" section. `TradeResult` rows with `round_trip_id=""` get all-N/A grades. Grade assignment loop skips them. Test case added. |
