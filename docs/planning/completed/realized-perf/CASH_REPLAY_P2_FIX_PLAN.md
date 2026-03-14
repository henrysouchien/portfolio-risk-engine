# Cash Replay Phase 2B Fix Plan

## Status Snapshot (2026-02-25)

Completed before this phase:
- Phase 1 cash replay hardening landed (unknown/fx filtering + futures exposure inference gating).
- Phase 2A synthetic-cash correction landed (synthetic cash events excluded from replay; synthetic sensitivity gate remains diagnostic/reliability only).
- Independent code review surfaced an observed-only branch bug and a weak regression.
- Follow-up patch landed:
  - observed-only NAV replay now excludes provider-authoritative flows
  - regression test now validates non-zero observed-vs-provider NAV impact under provider flows

Sequencing:
- This document is **Phase 2B** and assumes **Phase 2A** is already in place.
- Phase 2A reference: `docs/planning/CASH_REPLAY_P2_SYNTHETIC_FIX_PLAN.md`.

Verified current state:
- Provider-authoritative mode dominates in live runs (`inferred=0`).
- Reported returns are still materially wrong vs broker truth (for example IBKR source still strongly positive while broker baseline is negative).
- Root remaining distortion is futures full-notional cash replay contaminating month-end cash/NAV.

## Problem Statement

Even with inference gating fixed, realized cash replay still treats futures BUY/SELL as equity-like notional cash movements.
That injects large artificial cash swings into NAV reconstruction and Modified Dietz returns.

Secondary issue: overlapping non-external provider cash-flow rows and income rows can double-count internal cash effects.

## Decision Locks

1. Futures cash policy: **Provider-first + fee-only**
- Futures notional is excluded from replay cash deltas.
- Futures fees still affect replay cash.
- Futures P&L remains sourced from lot/FIFO analytics (not notional cash replay).

2. Income vs provider-flow overlap policy: **Prefer income rows**
- For matching internal cash legs, keep `INCOME` and drop matching non-external `PROVIDER_FLOW` rows.

3. Scope: **All providers with futures rows**
- Do not limit to IBKR-only logic.

## Goals and Success Criteria

1. Eliminate futures-notional-driven NAV spikes in March/April style windows.
2. Preserve provider-authoritative external-flow semantics and keep `inferred=0` where authoritative.
3. Remove deterministic income/provider-flow overlap double-counting.
4. Improve diagnostics to make cash-policy and overlap behavior auditable.

Success thresholds:
- `source=ibkr_flex` and `source=all` no longer show extreme positive monthly spikes driven by futures notional replay.
- For windows with futures activity, `futures_notional_suppressed_usd` is non-zero and `futures_fee_cash_impact_usd` stays in expected fee-scale range (not notional-scale).
- For overlap samples, `income_flow_overlap_dropped_net_usd` matches manual spot checks within `+/- $0.01` per matched pair set.
- Synthetic-impact and reconciliation diagnostics improve directionally and materially versus the post-P1 live trace.
- IBKR 2025 monthly directionality: for months where broker baseline magnitude is at least `0.50%`, system monthly return sign matches broker sign in at least `90%` of those months.

## Implementation Plan

### Workstream A: Futures Fee-Only Cash Replay

File:
- `core/realized_performance_analysis.py`

Changes:
1. In `derive_cash_and_external_flows`, branch cash-impact logic by instrument type:
- For `instrument_type == futures`:
  - `BUY/COVER`: cash delta = `-(fee * fx)`
  - `SELL/SHORT`: cash delta = `-(fee * fx)`
  - Other futures actions (`ADJUST`, fee-only rows, synthetic liquidation rows, unknown verbs): never replay notional cash; apply fee-only when fee is present, otherwise zero cash delta.
- For non-futures, keep existing BUY/SELL/SHORT/COVER cash logic.

2. Keep current futures open-position tracking (`_futures_positions`) and warnings unchanged.

3. Keep inference gating behavior unchanged (already fixed in P1).

4. Add explicit guards:
- Missing fee defaults to `0.0` for fee-only futures cash.
- Missing/invalid FX defaults to `1.0` with warning counter.
- Unknown futures actions increment a diagnostic counter and remain fee-only/zero-cash.

5. Add aggregate diagnostics collected during replay:
- `futures_notional_suppressed_usd`
- `futures_fee_cash_impact_usd`
- `futures_unknown_action_count`
- `futures_missing_fx_count`

### Workstream B: Income/Provider Internal Flow De-dup

Files:
- `core/realized_performance_analysis.py`

Changes:
1. Add helper before replay event construction:
- Build candidate key for income rows and non-external provider-flow rows:
  - provider/source (normalized)
  - institution/account identity
  - event date (day)
  - signed amount rounded to cents

Provider/source normalization contract (local to realized cash replay):
- `strip` leading/trailing whitespace
- uppercase
- collapse internal spaces/hyphens to underscores
- alias map applied after normalization (for example `IBKR_FLEX` -> `IBKR`, `INTERACTIVE_BROKERS` -> `IBKR`)

Alias-map maintenance + visibility:
- Implement alias map as a single constant in realized-performance analysis code (not duplicated across modules).
- Define that constant in `core/realized_performance_analysis.py` as `REALIZED_PROVIDER_ALIAS_MAP` (or equivalent single exported constant used by replay).
- Initial documented entries should include at least: `IBKR_FLEX -> IBKR`, `INTERACTIVE_BROKERS -> IBKR`.
- Any alias additions require a unit test that proves normalization behavior and dedupe matching for that alias.
- Surface normalization diagnostics with raw-provider -> normalized-provider sample pairs when mismatches are encountered.
- Document current alias entries in the code comment above the constant and keep examples synchronized with this plan.

Account identity precedence:
- `account_id`, else `account_number`, else stable institution+masked-account fallback

Matching rule:
- Must match normalized provider key and account identity
- Must match calendar day
- Must match signed amount within one cent tolerance (`abs(delta) <= 0.01`)

2. Drop matching non-external provider-flow rows when a matching income row exists.

3. Do not dedupe external flows (`is_external_flow=True`).

4. Emit diagnostics/warnings:
- dropped row count
- dropped net amount
- dropped counts by provider
- overlap candidate count
- alias-normalization mismatch sample counter

### Workstream C: Metadata + Contract Propagation

Files:
- `core/realized_performance_analysis.py`
- `core/result_objects/realized_performance.py`
- `core/performance_flags.py` (only if flag exposure needed)

Add to realized metadata (additive only):
- `futures_cash_policy` (`"fee_only"`)
- `futures_txn_count_replayed` (count of futures transaction rows processed by replay after date/source filters, regardless of whether resulting cash delta is zero or fee-only)
- `futures_notional_suppressed_usd`
- `futures_fee_cash_impact_usd`
- `futures_unknown_action_count`
- `futures_missing_fx_count`
- `income_flow_overlap_dropped_count`
- `income_flow_overlap_dropped_net_usd`
- `income_flow_overlap_dropped_by_provider`
- `income_flow_overlap_candidate_count`

Ensure serialization and agent snapshot include these in `data_quality` diagnostics.

## Tests

### Unit tests (new)

File:
- `tests/core/test_realized_performance_analysis.py`

1. `test_futures_cash_replay_fee_only_excludes_notional`
- Futures BUY/SELL change cash only by fees, not notional.

2. `test_futures_cash_replay_preserves_non_futures_cash_logic`
- Equity/option/cash events unaffected.

3. `test_income_provider_overlap_drops_non_external_flow`
- Matching income + non-external provider flow -> provider row dropped.

4. `test_income_provider_overlap_keeps_external_flow`
- Matching income + external provider flow -> both retained by design.

5. `test_income_provider_overlap_tolerance_one_cent`
- Verify amount/date matching tolerance behavior.

6. Keep and pass the new observed-only regression:
- `test_observed_only_nav_excludes_provider_flow_events`.

7. Add metadata diagnostics contract tests:
- serialized realized output includes all new futures/overlap fields
- agent snapshot `data_quality` block includes the same fields and stable types

### Integration/contract tests

Run and keep green:
- `tests/core/test_realized_performance_analysis.py`
- `tests/core/test_performance_flags.py`
- `tests/mcp_tools/test_performance.py`
- `tests/mcp_tools/test_performance_agent_format.py`

Add one integration assertion:
- replay diagnostics (`futures_notional_suppressed_usd`, overlap counters) are present and non-null in `format='full'` and `format='agent'` responses.

## Live Validation Procedure

1. Run full outputs after implementation:
- `get_performance(mode='realized', source in [all, ibkr_flex, schwab, plaid], format='full')`

2. Compare against baseline artifacts:
- `docs/planning/performance-actual-2025/baseline_extracted_data.json`

3. Confirm:
- No futures-notional style cash spikes in diagnostic traces.
- `flow_source_breakdown.inferred` remains zero on authoritative slices.
- `nav_pnl_synthetic_impact_usd` reflects real observed-vs-provider deltas.
- `income_flow_overlap_*` diagnostics reconcile with sampled raw rows (count/net checks).
- `futures_notional_suppressed_usd` is only non-zero in windows/accounts with futures transactions.
- Returns direction is consistent with broker baselines for major accounts.
- IBKR monthly sign-match target (`>=90%` where `|baseline| >= 0.50%`) is met or documented with residual exception reasons.

## Risks and Mitigations

1. Risk: fee-only futures replay may under-model variation margin timing.
- Mitigation: preserve FIFO P&L truth, monitor reconciliation gap and synthetic-impact metrics.

2. Risk: over-deduping provider flows and income.
- Mitigation: strict key match (provider/account/date/amount), keep external flows untouched, emit dropped-row diagnostics.

3. Risk: hidden behavior change for non-futures portfolios.
- Mitigation: dedicated regression test asserting unchanged non-futures cash replay paths.

## Out of Scope

- Upstream provider normalizer redesign.
- New backfill UX/workflow changes.
- Broader synthetic-position policy redesign beyond additive diagnostics.
