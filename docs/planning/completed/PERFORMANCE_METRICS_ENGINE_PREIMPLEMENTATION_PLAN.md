# Performance Metrics Engine Pre-Implementation Plan

**Status:** COMPLETE
**Parent:** Realized performance roadmap
**Scope Type:** Pre-implementation safety track (no behavior changes intended)
**Completed:** Extracted into `core/performance_metrics_engine.py` with 15 unit tests. Both hypothetical and realized pipelines use the shared engine.

---

## Why This Is Separate

Before adding `get_realized_performance`, we should isolate and harden the shared portfolio-level metric math (returns, volatility, Sharpe, drawdown, alpha/beta, benchmark comparison).  

This refactor is a standalone effort with strict parity guarantees so we do not accidentally change `get_performance` behavior.

---

## Goals

1. Extract reusable metric math into a pure core engine.
2. Keep existing `get_performance` outputs identical (shape, units, rounding, thresholds).
3. Create a stable interface so both hypothetical and realized pipelines can call the same engine.
4. Add characterization tests to catch any regression before realized implementation begins.

---

## Non-Goals

1. No changes to current `get_performance` API contract.
2. No new realized-performance endpoint in this phase.
3. No transaction-ingestion or FIFO changes in this phase.

---

## Current State (Coupling)

The metric calculations are currently bundled with data acquisition and preprocessing in:

- `portfolio_risk.calculate_portfolio_performance_metrics(...)`

This mixes:

1. Return-series data loading and filtering
2. Benchmark fetching/alignment
3. Risk-free rate lookup
4. Metric math
5. Response shaping and rounding

Result: difficult to safely reuse for realized return series without duplicate logic.

---

## Target Architecture

### New Core Module

Create:

- `core/performance_metrics_engine.py`

### Core Function (Pure)

- `compute_performance_metrics_from_series(...) -> dict`

Inputs (no external I/O):

1. `portfolio_returns` (monthly series)
2. `benchmark_returns` (monthly series, aligned or alignable)
3. `benchmark_ticker`
4. `risk_free_rate` (annual decimal)
5. `analysis_metadata` (period dates, months, optional notes)
6. `rounding_profile` (defaults that preserve current behavior)

Outputs:

1. Same metric sections currently returned by `calculate_portfolio_performance_metrics`:
   - `analysis_period`
   - `returns`
   - `risk_metrics`
   - `risk_adjusted_returns`
   - `benchmark_analysis`
   - `benchmark_comparison`
   - `monthly_stats`
   - `risk_free_rate`
   - `monthly_returns`
2. Optional warnings/errors in existing format.

### Adapter Pattern

Keep `portfolio_risk.calculate_portfolio_performance_metrics(...)` as the orchestration adapter that:

1. Loads data and builds return series exactly as today.
2. Calls the new pure function for metric math.
3. Preserves existing response structure and semantics.

---

## Compatibility Contract (Must Hold)

For `get_performance` paths:

1. Field names unchanged.
2. Units unchanged (`%` fields remain percent values, not decimals).
3. Rounding unchanged.
4. Data quality thresholds unchanged.
5. Error messages/keys unchanged where currently relied upon.
6. Benchmark alignment behavior unchanged.
7. Risk-free fallback behavior unchanged.

---

## Implementation Phases

## Phase 0: Lock Current Behavior (Characterization)

Add tests that snapshot current outputs from stable fixtures for:

1. Normal case (valid portfolio + benchmark)
2. Edge case: limited observations
3. Edge case: benchmark overlap failure
4. Edge case: risk-free fallback path

Gate: tests are green against current implementation before refactor.

## Phase 1: Introduce Pure Metrics Engine

1. Implement `core/performance_metrics_engine.py` with no external API calls.
2. Port metric calculations only.
3. Keep internal comments explicit around units and annualization assumptions.

Gate: unit tests for pure function calculations pass.

## Phase 2: Wire Adapter to Engine

1. Update `portfolio_risk.calculate_portfolio_performance_metrics` to call the engine.
2. Preserve existing output keys and rounding.
3. Keep existing pre/post checks in adapter.

Gate: characterization tests from Phase 0 remain identical.

## Phase 3: Service/MCP Regression Pass

Run regression checks for:

1. `services/portfolio_service.analyze_performance(...)`
2. `mcp_tools/performance.py` formats: `summary`, `full`, `report`

Gate: no observable change in successful and error responses.

---

## Test Matrix

1. **Math parity tests**: old vs new on same aligned series.
2. **Contract tests**: key presence, key naming, value types.
3. **Numerical drift tolerance**: exact equality where rounded; tiny tolerance only pre-round.
4. **Edge behavior tests**:
   - zero volatility
   - insufficient CAPM observations
   - empty overlap with benchmark
   - missing treasury data fallback

---

## Risks and Mitigations

1. **Rounding drift**  
Mitigation: centralize rounding profile and parity tests on rounded outputs.

2. **Unit confusion (decimal vs percent)**  
Mitigation: explicit docstrings and unit assertions in tests.

3. **Behavior change in error handling**  
Mitigation: preserve adapter-level error paths and message formats.

4. **Hidden coupling in downstream formatters**  
Mitigation: run end-to-end checks for `PerformanceResult` summary/full/report.

---

## Definition of Done

1. New pure metrics engine exists and is unit tested.
2. Existing `get_performance` behavior is unchanged by characterization tests.
3. Service and MCP integration tests pass for all three output formats.
4. Refactor is documented as a completed prerequisite for realized-performance implementation.

---

## Suggested Parallel Track (Design Review)

If you want this reviewed independently before coding, run a design-only pass focused on:

1. function signature for `compute_performance_metrics_from_series`
2. edge-case policy (missing benchmark overlap, sparse data)
3. numeric conventions (annualization, regression minima, rounding)
4. migration safety checklist and rollback plan

This can be approved before any realized-performance implementation begins.

