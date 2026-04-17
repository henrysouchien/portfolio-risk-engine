# Overview Editorial Pipeline — Phase 2A Implementation Plan

**Status**: DRAFT — pending Codex review
**Created**: 2026-04-13
**Inputs**:
- Architecture spec: `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md` (sections 3.1, 7, 14)
- Audit findings: `docs/planning/EDITORIAL_PIPELINE_AUDIT.md` (Gaps 2, 7, 8)
- Phase 1 plan pattern: `docs/planning/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md`

**Scope**: Three independently committable workstreams addressing the top gaps identified in the Editorial Pipeline Audit (2026-04-13):

1. **Loss Screening Generator** (P1 — highest-value new generator for the persistent surface)
2. **Events Generator** (P1 — pull-forward from Phase 2 scope, time-bounded persistent content)
3. **Benchmark Comparison Enrichment** (P2 — metric strip schema enrichment for side-by-side values)

**Estimated timeline**: ~11 working days (~2.5 weeks). Critical path: A1→A2→A6→A7→A8. Parallel branches (A5, A4, A3) fit within this window.

---

## 1. Sub-phase Summary

| # | Sub-phase | Scope | Duration | Depends on | Commits |
|---|---|---|---|---|---|
| A1 | Schema additions: `loss_screening` category + `benchmark_value` field | `models/overview_editorial.py` + frontend TS types + adapter | ~2 days | — | 1 |
| A2 | Positions snapshot enrichment for loss data | `core/overview_editorial/orchestrator.py` `_normalize_positions()` | ~2 days | A1 | 1 |
| A3 | Loss Screening Generator | `core/overview_editorial/generators/loss_screening.py` | ~3 days | A2 | 1 |
| A4 | Benchmark Comparison Enrichment (generators + frontend) | Performance generator + MetricStrip.tsx + adapter | ~2 days | A1 | 1 |
| A5 | Events cached builder | `services/portfolio/result_cache.py` + new `get_events_result_snapshot()` | ~3 days | — | 1 |
| A6 | Orchestrator events data source | `core/overview_editorial/orchestrator.py` sequential after positions + `services/events_service.py` | ~2 days | A2, A5 | 1 |
| A7 | Events Generator | `core/overview_editorial/generators/events.py` | ~3 days | A6 | 1 |
| A8 | Policy + wiring + integration | Policy layer updates, `__init__.py` exports, integration tests | ~2 days | A3, A4, A7 | 1 |

**Total committable units**: 8
**Critical path duration**: ~11 working days (A1→A2→A6→A7→A8). Parallel branches (A5, A4, A3) fit within this window. **Wall-clock estimate**: ~11 working days (~2.5 weeks).
**Parallelizable work**: A5 (events cache) runs in parallel with A1-A2. A4 (benchmark) runs in parallel with A2-A3. A3 (loss screening) and A7 (events generator) run in parallel after their dependencies.

---

## 2. Dependency Graph

```
A1 (schema: category + benchmark_value)
  ├──> A2 (positions snapshot enrichment: loss_positions + all_tickers_with_weights)
  │      ↓
  │    A3 (loss screening generator)
  │      ↓
  │      ├──────────────────────────> A8 (policy + wiring)
  │      │                             ↑
  │      └──> A6 (events orchestrator, sequential after positions) ──┤
  │                ↑                   ↑
  └──> A4 (benchmark enrichment) ──────┤
                                       │
A5 (events cached builder) ──> A6 ─────┤
                                       │
A7 (events generator) ────────────────>┘
```

**Critical path**: A1 → A2 → A6 → A7 → A8 (~11 working days / ~2.5 weeks). A6 depends on BOTH A2 (for `all_tickers_with_weights`) and A5 (for the events cache).

**Parallelism**: A5 (events cache) runs in parallel with A1-A2. A4 (benchmark) runs in parallel with A2-A3. A3 (loss screening) and A7 (events generator) run in parallel after their respective dependencies.

---

## 3. Cross-Cutting Concerns

### 3.1 Wire schema authority

The backend Pydantic model at `models/overview_editorial.py` remains the single source of truth. Any change to `MetricStripItem` or `InsightCandidate` requires matching updates in:
- `frontend/packages/connectors/src/adapters/BackendBriefAdapter.ts` (adapter)
- `frontend/packages/ui/src/components/design/MetricStrip.tsx` (TS interface)

Same-commit rule from Phase 1 still applies.

### 3.2 Category Literal extension

`InsightCandidate.category` at `models/overview_editorial.py:89-99` must add `"loss_screening"`. The existing `"events"` category is already present. The `"loss_screening"` category is preferred over reusing `"tax"` because loss screening is about position health awareness, not just tax harvesting — it also covers thesis validation, exit decision prompting, and position drift detection.

### 3.3 `actions/` boundary test

The architecture boundary test at `tests/test_architecture_boundaries.py:200` enforces that `actions/` cannot import `fastapi` or `mcp_tools`. All new code respects this. New generators live in `core/`, not `actions/`.

### 3.4 Auth pattern

Dict-based auth: `user["user_id"]`, `user["email"]`. No `user.id` attributes.

### 3.5 Cache invalidation

No new write paths are introduced in Phase 2A. The existing three hook sites (`workers/tasks/positions.py:54`, `routes/onboarding.py:835,886`, `set_editorial_memory` via `_fire_invalidation_callbacks()`) cover all mutation paths. The new events cached builder (A5) is added to `clear_result_snapshot_caches()` so that when `invalidate_brief_cache()` fires, the events cache is also evicted — ensuring the next regenerated brief reads fresh events data alongside fresh risk/performance data.

### 3.6 Failure mode coverage

Each new generator follows the existing pattern: wrap the entire `generate()` body in `try/except`, log the exception, return `GeneratorOutput()` on failure. The policy layer continues to compose briefs with however many candidates are available. If all generators fail, `BriefNoCandidatesError` propagates to the fallback path as before.

---

## 4. Sub-phase A1 — Schema Additions

### 4.1 Goal

Add `"loss_screening"` to the `InsightCandidate.category` Literal and `benchmark_value` field to `MetricStripItem`. Wire through frontend TS types and adapter.

### 4.2 Files to modify

| File | Change |
|---|---|
| `models/overview_editorial.py` | Add `"loss_screening"` to category Literal; add `benchmark_value: str \| None = None` to `MetricStripItem` |
| `frontend/packages/ui/src/components/design/MetricStrip.tsx` | Add `benchmarkValue?: string` to TS interface |
| `frontend/packages/connectors/src/adapters/BackendBriefAdapter.ts` | Map `benchmark_value` -> `benchmarkValue` in `adaptMetricStrip` |

### 4.3 Changes

**1. Add `"loss_screening"` to `InsightCandidate.category` Literal** at `models/overview_editorial.py`:

The category Literal currently includes: `"concentration"`, `"risk"`, `"performance"`, `"income"`, `"trading"`, `"factor"`, `"tax"`, `"events"`, `"portfolio_mix"`. Add `"loss_screening"` after `"events"`.

**2. Add `benchmark_value` field to `MetricStripItem`**:

Add `benchmark_value: str | None = None` after the existing `context_label` field. This is a structured field for the benchmark comparison value (e.g., "1.00", "0.77"), separate from the `context_label` label text (e.g., "vs SPY"). The model uses `extra="forbid"` so this must be explicitly added.

**3. Extend frontend `MetricStripItem` TS interface** at `MetricStrip.tsx`:

Add `benchmarkValue?: string` to the existing interface. Render as small secondary text below the detail line, styled in dim text (e.g., "BMK: 1.00").

**4. Update `BackendBriefAdapter.ts` `adaptMetricStrip`**:

Map `benchmark_value` to `benchmarkValue` in the metric item mapping.

### 4.4 Tests (4 tests)

1. Pydantic round-trip: `MetricStripItem` with `benchmark_value` serializes and deserializes correctly
2. Backward compatibility: existing items without `benchmark_value` still validate
3. `InsightCandidate` with `"loss_screening"` category validates
4. Frontend adapter maps `benchmark_value` to `benchmarkValue`

### 4.5 Acceptance gate

- `pytest tests/core/overview_editorial/` passes
- Frontend adapter test passes
- No existing tests broken

### 4.6 Risks and rollback

- **Risk**: `extra="forbid"` means any typo in the field name causes a validation error. Mitigated by unit test.
- **Rollback**: Revert single commit. Field is optional — no data migration needed.

---

## 5. Sub-phase A2 — Positions Snapshot Enrichment

### 5.1 Goal

Extend `_normalize_positions()` in the orchestrator to include unrealized loss data for loss screening.

### 5.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `loss_positions` key to positions snapshot |

### 5.3 Changes

The current `_normalize_positions()` only extracts top holdings by weight (via `get_top_holdings(10)`) with `ticker`, `weight_pct`, `value`, and `type`. It does NOT include `cost_basis`, `pnl`, or any P&L data.

Add a new `loss_positions` list to the snapshot dict containing all non-cash positions sorted by unrealized P&L (ascending — worst losses first), with each entry including:
- `ticker`: str
- `value`: float (current market value)
- `cost_basis`: float or None
- `weight_pct`: float
- `pnl_dollar`: float or None (in position's basis currency)
- `pnl_usd`: float or None (USD-normalized for cross-currency ranking)
- `pnl_pct`: float or None

**P&L calculation**: Reuse the logic from `PositionResult._build_monitor_payload()` at `core/result_objects/positions.py:397-404`, which correctly handles shorts, sign conventions, and FX. Do NOT use naive `value - cost_basis` — that is wrong for short positions and FX-denominated holdings. The existing method computes `dollar_pnl = (raw_price - entry_price) * quantity` with quantity sign awareness, and also exposes `pnl_usd` and `pnl_basis_currency` for multi-currency portfolios. Extract or call the existing helper rather than reimplementing.

**Multi-currency ranking**: "Top 10 worst losers by dollar amount" uses `pnl_usd` (USD-normalized) for ranking, so losses in GBP/EUR/JPY positions are comparable. Display uses `pnl_dollar` (basis currency) for the user-facing headline.

Filter: only include positions where `cost_basis` is valid (not None, not NaN, not zero — following the existing `_is_valid_cost_basis` check pattern from `PositionResult`). Only include positions with negative `pnl_dollar` (underwater). Limit to top 10 worst losers by dollar amount.

**Full ticker/weight map for events**: Also add an `all_tickers_with_weights` dict to the positions snapshot: `{ticker: weight_pct}` for ALL positions (not just top 10). This is needed by the events data source (A6) to pass pre-loaded tickers to the events service helper and to enrich events with portfolio weights. The current `holdings` only has the top 10.

Preserve backward compatibility: existing `holdings`, `total_value`, `hhi`, `position_count` keys remain unchanged. `loss_positions` and `all_tickers_with_weights` are additive.

### 5.4 Tests (3 tests)

1. Loss positions extracted correctly: positions with cost_basis yield correct `pnl_dollar` and `pnl_pct`
2. Missing cost_basis positions are excluded
3. Only losing positions included: positive P&L positions filtered out

### 5.5 Acceptance gate

- Existing orchestrator tests pass unchanged
- `_normalize_positions` backward-compatible

### 5.6 Risks and rollback

- **Risk**: Position data may have inconsistent cost_basis across brokerages. Mitigated by filtering invalid cost_basis.
- **Rollback**: Revert commit. No downstream consumers until A3.

---

## 6. Sub-phase A3 — Loss Screening Generator

### 6.1 Goal

New generator that screens for positions with large unrealized losses and emits persistent attention cards.

### 6.2 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/loss_screening.py` | Loss screening generator | ~150 |
| `tests/core/overview_editorial/test_loss_screening_generator.py` | Unit tests | ~200 |

### 6.3 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/__init__.py` | Add export |

### 6.4 Design

```python
class LossScreeningInsightGenerator:
    name = "loss_screening"
    source_tool = "positions"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        ...
```

**Data source**: `context.tool_snapshot("positions")` — reads from `loss_positions` list added in A2.

**Candidates emitted**:

1. **`attention_item` candidates** (primary output — persistent cards for underwater positions):

   For each position in `loss_positions` (up to 3 worst losers), emit an `attention_item` with:
   - `category`: `"loss_screening"`
   - `headline`: e.g., `"PCTY is down 39% (-$5,023 unrealized) — hold or harvest?"`
   - `urgency`: Based on loss magnitude:
     - `"alert"` if pnl_pct <= -30% OR pnl_dollar <= -$5,000
     - `"act"` if pnl_pct <= -15% OR pnl_dollar <= -$2,000
     - `"watch"` otherwise
   - `action`: ExitRamp to `check_exit_signals` — `{"label": "Check exit signals", "action_type": "chat_prompt", "payload": "Check exit signals for PCTY"}`

   Scoring:
   - `relevance_score`: scaled by dollar loss magnitude, min 0.5, max 1.0
   - `urgency_score`: 0.95 for alert, 0.75 for act, 0.5 for watch
   - `novelty_score`: 0.7 (loss positions are always novel — unresolved action items)

2. **`margin_annotation` candidates** (thesis validation prompts):

   For the top 1-2 worst losers, emit a `MarginAnnotation` of type `"ask_about"`:
   - `anchor_id`: `"artifact.overview.concentration"`
   - `content`: e.g., `"Ask whether PCTY thesis still holds at -39%"`
   - `prompt`: e.g., `"Walk me through whether PCTY still makes sense at a -39% loss. Should I harvest the tax loss or hold?"`

3. **Tax-loss harvest exit ramp**: For positions where `pnl_dollar < -$1,000`, include a second exit ramp:
   - `{"label": "Tax-loss harvest analysis", "action_type": "chat_prompt", "payload": "Run tax-loss harvest analysis for my portfolio"}`

**Screening thresholds** (minimum to surface):
- `pnl_pct <= -10%` OR `pnl_dollar <= -$1,000`
- Below these thresholds, losses don't warrant persistent attention

**No metric or lead_insight candidates**: Loss screening emits `attention_item` and `margin_annotation` only. The metric strip is for portfolio-level statistics; individual position losses belong on attention cards. Loss screening should not compete for the lead insight slot — it's a persistent attention surface, not a lead story.

### 6.5 Tests (7 tests)

1. Empty loss_positions yields empty output
2. Single large loser emits attention_item with `urgency="alert"` (PCTY at -39%, -$5K)
3. Moderate loser emits attention_item with `urgency="act"` (-12%, -$1,500)
4. Small loss below threshold is filtered (-5%, -$200)
5. Margin annotation emitted for worst loser
6. Exit ramps include tax-loss harvest for large dollar losses
7. Generator gracefully handles failed positions data

### 6.6 Acceptance gate

- All 7 tests pass
- Generator follows the exact same pattern as `ConcentrationInsightGenerator`
- `InsightCandidate.category = "loss_screening"` validates (depends on A1)
- No imports from `fastapi` or `mcp_tools`

### 6.7 Risks and rollback

- **Risk**: `editorial_preferences.less_interested_in` might suppress loss_screening. Acceptable — user explicitly deprioritized it.
- **Risk**: Loss data may be stale if cost_basis hasn't been refreshed. Mitigated: PositionService refreshes on sync.
- **Rollback**: Revert commit + remove from `__init__.py`.

---

## 7. Sub-phase A4 — Benchmark Comparison Enrichment

### 7.1 Goal

Populate `benchmark_value` on metric candidates from the performance generator, and render in the frontend.

### 7.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/performance.py` | Populate `benchmark_value` on metric candidates |
| `core/overview_editorial/orchestrator.py` | Extend `_normalize_performance()` with benchmark fields |
| `frontend/packages/ui/src/components/design/MetricStrip.tsx` | Render benchmark value as secondary text |

### 7.3 Changes

**1. Extend performance normalization** in `orchestrator.py` `_normalize_performance()`:

Add benchmark-specific values to the snapshot dict. Available fields are in the performance agent snapshot's `benchmark` subsection (verified at `core/result_objects/performance.py:320` and `core/result_objects/realized_performance.py:557`):
- `"benchmark_return_pct"`: from the benchmark returns section
- `"benchmark_sharpe"`: if available in the benchmark risk section

Note: `benchmark_max_drawdown_pct` does NOT exist in the current performance snapshot. Do not include it.

**2. Performance generator populates `benchmark_value`**:

- **Beta metric**: `"benchmark_value": "1.00"` (beta of the benchmark is always 1.00 by definition)
- **Sharpe metric**: benchmark Sharpe if available from snapshot
- **Return metric**: benchmark return if available
- **Alpha metric**: no benchmark_value needed (alpha IS the benchmark comparison)
- **Max Drawdown metric**: no benchmark_value (benchmark max drawdown not available in current snapshot)

**3. Frontend rendering**: `benchmarkValue` renders as small secondary text below the detail line.

### 7.4 Tests (4 tests)

1. Beta metric includes benchmark_value "1.00"
2. Return metric includes benchmark return when available
3. Benchmark value is None when data unavailable
4. Orchestrator normalization includes benchmark fields

### 7.5 Acceptance gate

- Performance generator tests pass
- Existing metric strip rendering unaffected when `benchmark_value` is None
- New benchmark value renders correctly

### 7.6 Risks and rollback

- **Risk**: Benchmark data may not always be available. Mitigated: `benchmark_value` is optional.
- **Rollback**: Revert commit. `benchmark_value: None` is backward-compatible.

---

## 8. Sub-phase A5 — Events Cached Builder

### 8.1 Goal

Add a cached builder for events data in `result_cache.py`, following the existing pattern. This unblocks the events generator (deferred from Phase 1 per arch spec §3.1).

### 8.2 Files to modify

| File | Change |
|---|---|
| `services/portfolio/result_cache.py` | Add events cache + `get_events_result_snapshot()` |

### 8.3 Changes

**1. Add events cache + inflight dict** following the existing pattern:

```python
_events_cache: TTLCache[str, Any] = TTLCache(maxsize=64, ttl=_CACHE_TTL_SECONDS)
_events_inflight: dict[str, Future[Any]] = {}
```

**2. Add `get_events_result_snapshot()` function**:

```python
def get_events_result_snapshot(
    *,
    user_id: int,
    portfolio_name: str,
    event_types: str,        # "earnings,dividends" or "all"
    days_ahead: int,          # default 14
    builder: Callable[[], T],
    use_cache: bool = True,
) -> T:
```

Cache key: `f"{user_id}:{portfolio_name}:{event_types}:{days_ahead}"`

The `builder` callable calls the actual FMP events API. Cached builder pattern means the live FMP call only happens on cache miss, and concurrent requests share the inflight future.

**3. Add to `clear_result_snapshot_caches()`**: clear `_events_cache` and `_events_inflight`.

### 8.4 Tests (3 tests)

1. Cache hit returns cloned value
2. Cache miss calls builder
3. Concurrent requests share inflight future

### 8.5 Acceptance gate

- `result_cache.py` internally consistent
- `clear_result_snapshot_caches()` includes the new cache
- No import of `fmp` or `mcp_tools` from `result_cache.py`

### 8.6 Risks and rollback

- **Risk**: The 30s default TTL may be too short for events data. Consider a longer TTL (300s) via `EVENTS_SNAPSHOT_TTL_SECONDS`. For Phase 2A, same 30s is acceptable.
- **Rollback**: Revert commit. No downstream consumers until A6.

---

## 9. Sub-phase A6 — Orchestrator Events Data Source

### 9.1 Goal

Add events as a sequential data source in the orchestrator, running after positions are loaded (events needs the ticker list and weight map from positions to avoid duplicate loading and to enrich events with portfolio weights).

### 9.2 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `services/events_service.py` | Service-layer events helper (wraps FMP calendar call + weight enrichment) | ~80 |

### 9.3 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `_gather_events()` + `_normalize_events()` (sequential after positions, no worker count change) |

### 9.4 Changes

**1. Two-phase gathering** — events depends on positions being loaded first (for ticker list + weights), so it cannot be fully parallel with the initial 3 lanes. The orchestrator uses a two-phase approach:

- **Phase 1 (parallel)**: `_gather_positions()`, `_gather_risk()`, `_gather_performance()` — same as today, 3 lanes in ThreadPoolExecutor.
- **Phase 2 (sequential, after phase 1 completes)**: `_gather_events(ticker_list, weight_map)` — uses the positions result from phase 1 to pass pre-loaded tickers and weights. Calls `get_events_result_snapshot()` (from A5's cached builder in `result_cache.py`) with a builder that delegates to the events service helper (`services/events_service.py`). This avoids the duplicate position loading that `get_portfolio_events_calendar()` would otherwise do via `_load_portfolio_symbols()`.

This is a minor structural change to the existing `gather()` method: the current code submits all 3 futures then collects them. The new code submits 3, collects, then submits events as a 4th step. Total latency increases by the events call duration (~200ms cached), which is acceptable.

**Alternative**: If the events call latency becomes a concern, phase 2 can run events in parallel with a second ThreadPoolExecutor batch alongside post-processing of phase 1 results. For Phase 2A, sequential is simpler and sufficient.

**2. New `services/events_service.py` helper** — extracts the events workflow into the service layer to avoid a `core/ → mcp_tools/` import. The service helper:
- Accepts a pre-loaded ticker list + weight map (from positions result)
- Calls the FMP events calendar API (via `fmp/tools/events.py` directly, not through `mcp_tools/news_events.py`)
- Enriches each event with portfolio weight from the weight map
- Computes `days_until` from event date vs today
- Returns the enriched events list

**3. Add `_normalize_events()` helper** to convert the service result into `{snapshot, flags}` dict:
- `events`: list of `{ticker, event_type, date, days_until, weight_pct}` dicts (enriched by the service helper)
- `event_count`: total count
- `next_event_date`: ISO string of soonest event
- `has_earnings_this_week`: boolean

**4. ThreadPoolExecutor `max_workers`** stays at 3 for the initial parallel batch. Events runs sequentially after. (Phase 2B will add more parallel lanes.)

### 9.5 Tests (4 tests)

1. Events data source loads successfully
2. Events failure is graceful (other sources unaffected)
3. Existing data sources unaffected
4. Events service helper enriches events with portfolio weights

### 9.6 Acceptance gate

- Existing orchestrator tests pass
- Events data appears in `PortfolioContext.tool_results["events"]`
- No `mcp_tools` imports in `core/overview_editorial/` (layering clean)
- Events cache included in `clear_result_snapshot_caches()` (from A5)

### 9.7 Risks and rollback

- **Risk**: FMP API rate limits. Cached builder mitigates (at most ~2 calls/min/user).
- **Risk**: Events service helper is a new file. Mitigated: thin wrapper, delegates to existing FMP functions.
- **Rollback**: Revert commit + delete `services/events_service.py`. Orchestrator reverts to 3 data sources.

---

## 10. Sub-phase A7 — Events Generator

### 10.1 Goal

New generator for time-bounded portfolio events (earnings, dividends) as persistent attention cards.

### 10.2 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/events.py` | Events generator | ~180 |
| `tests/core/overview_editorial/test_events_generator.py` | Unit tests | ~200 |

### 10.3 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/__init__.py` | Add export |

### 10.4 Design

```python
class EventsInsightGenerator:
    name = "events"
    source_tool = "events"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        ...
```

**Candidates emitted**:

1. **`attention_item` candidates** (countdown-style persistent cards):

   For each event within 7 days, emit an `attention_item`:
   - `headline`: Countdown-style, e.g., `"MSCI Q1 earnings in 5 days (10% position)"`
   - `urgency`:
     - `"alert"` if within 2 days AND weight >= 5%
     - `"act"` if within 7 days AND weight >= 3%
     - `"watch"` otherwise
   - `action`: ExitRamp to navigate — `{"label": "Review position", "action_type": "navigate", "payload": "holdings"}`

   Scoring:
   - `relevance_score`: scaled by position weight, min 0.4, max 0.95
   - `urgency_score`: inverse of days until event (tomorrow = 1.0, 7 days = 0.5)
   - `novelty_score`: 0.8 for events within 3 days, 0.5 for further out

2. **`metric` candidates** (single low-priority metric):

   If upcoming events within 7 days exist:
   - `id`: `"nextEvent"`
   - `title`: `"Next Event"`
   - `value`: e.g., `"MSCI earnings Tue"` or `"2 earnings this week"`
   - Low priority: relevance_score 0.3, urgency_score 0.4

3. **`margin_annotation` candidates**: For earnings on large positions (>5% weight), emit a `context` annotation.

**Event type handling**: Earnings > Dividends > Splits in priority.

**Deduplication**: Same ticker with multiple events merged into single attention card.

### 10.5 Tests (7 tests)

1. No events yields empty output
2. Earnings within 3 days emits alert attention_item
3. Earnings 7 days out emits watch attention_item
4. Multiple events produce multiple attention_items (up to 3)
5. Next event metric emitted when events exist
6. No metric when no events within 7 days
7. Graceful handling of failed events data

### 10.6 Acceptance gate

- All tests pass
- Countdown headline formatting correct
- `InsightCandidate.category = "events"` already in schema

### 10.7 Risks and rollback

- **Risk**: Events data may have stale dates. Generator filters events where `date < today`.
- **Risk**: FMP returns events without portfolio weight. Use 0% and skip weight-based urgency boost.
- **Rollback**: Revert commit + remove from `__init__.py`.

---

## 11. Sub-phase A8 — Policy + Wiring + Integration

### 11.1 Goal

Wire new generators into the policy layer and verify end-to-end integration.

### 11.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/__init__.py` | Export new generators |
| `core/overview_editorial/policy.py` | Register new generators, update confidence thresholds |

### 11.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `tests/core/overview_editorial/test_phase2a_integration.py` | Integration tests | ~200 |

### 11.4 Changes

**1. Update `EditorialPolicyLayer.__init__`** to include new generators:

```python
self._generators = generators or [
    ConcentrationInsightGenerator(),
    RiskInsightGenerator(),
    PerformanceInsightGenerator(),
    LossScreeningInsightGenerator(),
    EventsInsightGenerator(),
]
```

**2. Update confidence/source calculations**: Change hardcoded `== 3` to core-source logic. Both `_confidence()` and `_source()` at `policy.py:284` are updated:

```python
_CORE_SOURCES = {"positions", "risk", "performance"}

def _confidence(self, context):
    core_loaded = sum(1 for s in _CORE_SOURCES if context.data_status.get(s) == "loaded")
    if core_loaded == 3: return "high"
    if core_loaded >= 1: return "partial"
    return "summary only"

def _source(self, context):
    core_loaded = sum(1 for s in _CORE_SOURCES if context.data_status.get(s) == "loaded")
    if core_loaded == 3: return "live"
    if core_loaded >= 1: return "mixed"
    return "summary"
```

This means supplementary sources (events, income, trading, factor, tax) are enrichment — their absence does not degrade confidence. This logic is shared with Phase 2B (whichever ships first implements it; the other inherits).

### 11.5 Integration tests (5 tests)

1. Full pipeline with all 5 generators produces brief with metrics + lead_insight + attention_items
2. Loss screening attention_items compete with concentration attention_items via scoring
3. Events metric competes with other metrics in the 6-slot selection
4. Partial data (events fail) — brief generates correctly with 3/4 sources
5. Empty loss positions + no events — brief identical to Phase 1 output (regression)

### 11.6 Acceptance gate

- All existing tests pass (regression)
- PCTY-like position appears as attention_item
- Upcoming earnings appear as attention_item
- Beta metric shows `benchmark_value: "1.00"`

### 11.7 Risks and rollback

- **Risk**: New generators produce too many candidates. Mitigated: loss screening emits attention_items only (not metrics), events emit at most 1 low-priority metric.
- **Rollback**: Revert commit. Policy layer reverts to 3 generators.

---

## 12. Implementation Schedule

**Week 1**:
- A1 (schema additions) — 2 days
- A5 (events cached builder) — 3 days, parallel with A1

**Week 2**:
- A2 (positions enrichment: loss_positions + all_tickers_with_weights) — 2 days
- A4 (benchmark enrichment) — 2 days, parallel with A2
- A6 (orchestrator events data source, sequential after positions) — 2 days, after A2 + A5

**Week 3**:
- A3 (loss screening generator) — 3 days
- A7 (events generator) — 3 days, parallel with A3

**Week 4** (half-week):
- A8 (policy + wiring + integration) — 2 days

**Total: ~11 working days (~2.5 weeks)**

---

## 13. QA Checklist

Before shipping Phase 2A:

1. Load overview for founder portfolio — verify losing position (PCTY or equivalent) appears as attention_item candidate
2. Verify beta metric shows `benchmark_value: "1.00"` rendered as secondary text
3. Verify upcoming events (if any) appear as attention_item candidates
4. Verify "PREVIOUSLY" banner and diff markers still work
5. Kill events FMP call (mock failure) — verify overview loads with 3 data sources
6. Verify no `fastapi` imports in `core/overview_editorial/generators/`
7. All existing tests pass (full pytest run)
8. Check telemetry: `overview_brief_generated` shows increased `candidates_considered`
