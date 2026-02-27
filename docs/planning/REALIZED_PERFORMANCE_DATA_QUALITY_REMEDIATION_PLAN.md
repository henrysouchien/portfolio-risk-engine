# Realized Performance Data Quality Remediation Plan (Phase 1)

## Summary
This phase fixes the highest-impact correctness issue first: per-source realized runs are contaminated because transactions are source-filtered but holdings are not.

We will implement source-scoped holdings alignment, add a soft reliability gate, and lock behavior with regression tests using the 2025 baseline fixture.

Chosen decisions:
- Reliability behavior: Soft Gate
- Delivery scope: Phase 1 only (source scoping + soft gate now; backfill workflow deferred)

Decision locks in this document remove implementer ambiguity for:
- non-consolidated holdings input
- deterministic source attribution (especially `ibkr_flex`)
- `reliable` vs `high_confidence_realized` semantics
- post-fix regression assertions (not pinned to known-bad pre-fix values)

## Goals and Success Criteria
1. Per-source realized outputs (`schwab`, `plaid`, `snaptrade`, `ibkr_flex`) use only holdings attributable to that source for coverage/synthetic logic.
2. Agent/full outputs clearly mark low-confidence runs without hiding metrics (soft gate).
3. Snapshot/report fields make root cause inspectable (coverage, synthetic impact, source contamination flags).
4. Regression tests enforce expected source coverage and key baseline invariants.

## In Scope (Phase 1)
- Source-scoped holdings attribution in realized analysis path.
- Soft reliability indicator contract additions in output.
- Enhanced diagnostics fields in `realized_metadata` and agent snapshot.
- Tests using `tests/fixtures/performance_baseline_2025.json`.

## Out of Scope (Phase 1)
- Manual backfill UX/workflow improvements.
- Reworking synthetic lot construction policy.
- Refactoring provider integrations (SnapTrade/IBKR API behavior itself).

## Public/API/Type Changes
### 1) `get_performance(..., mode="realized", format="agent"|"full")`
Add/standardize these fields:

- `snapshot.data_quality.reliable` (bool)
- `snapshot.data_quality.reliability_reasons` (string[])
- `snapshot.data_quality.synthetic_impact_usd` (number)
- `snapshot.data_quality.holdings_scope` (enum: `source_scoped`, `institution_scoped`, `consolidated`)
- `snapshot.data_quality.source_transaction_count` (int)
- `snapshot.data_quality.source_holding_count` (int)
- `snapshot.data_quality.cross_source_holding_leakage_count` (int)
- `snapshot.data_quality.reliability_reason_codes` (string[])

For `format="full"` under `realized_metadata`:
- `reliable` (bool)
- `reliability_reasons` (string[])
- `holdings_scope` (string)
- `source_holding_symbols` (string[])
- `source_holding_count` (int)
- `source_transaction_count` (int)
- `cross_source_holding_leakage_symbols` (string[])
- `reliability_reason_codes` (string[])

### 2) Soft Gate Rules (no metric nulling in Phase 1)
`reliable` semantics in Phase 1:
- `reliable := high_confidence_realized`
- `reliability_reasons` is derived from the existing confidence-failure reasons/warnings.

Reason contract (decision lock):
- `reliability_reason_codes` must be stable machine-readable values (derived from `data_quality_flags.code` and deterministic gate checks), while
- `reliability_reasons` remains human-readable text.
- Initial code set for Phase 1:
  - `LOW_DATA_COVERAGE`
  - `ZERO_SOURCE_TRANSACTIONS`
  - `SYNTHETIC_PNL_SENSITIVITY`
  - `NAV_METRICS_ESTIMATED`
  - `HIGH_SEVERITY_UNPRICEABLE`
  - `INCOMPLETE_TRADES_EXCEED_LIMIT`
  - `RECONCILIATION_GAP_EXCEED_LIMIT`

Set `reliable=false` when any of:
- high-confidence gate fails
- source transaction count is zero
- synthetic sensitivity flag is high severity

Metrics remain present, but:
- `performance_category` enum remains unchanged (`excellent|good|fair|poor|unknown`) for backward compatibility.
- `key_insights` prepends reliability warning.
- `flags` includes an explicit reliability warning flag.

## Implementation Plan
### Workstream A: Source-Scoped Holdings Alignment
Files:
- `core/realized_performance_analysis.py`
- `trading_analysis/data_fetcher.py`
- `services/position_service.py` (read path only if needed to reuse attribution fields)

Changes:
0. For realized mode with `source != "all"`, load holdings with `consolidate=False` so source attribution is preserved.
1. Build a source-attributed holdings subset in realized mode:
   - `source="schwab"` => `position_source == schwab`
   - `source="plaid"` => `position_source == plaid`
   - `source="snaptrade"` => `position_source == snaptrade`
   - `source="ibkr_flex"` => holdings attributed to Interactive Brokers accounts by deterministic account/institution identity (not by raw `position_source` string alone).
2. Deterministic attribution precedence (decision complete):
   - Primary: account identity/institution match (Interactive Brokers account IDs/institution names for `ibkr_flex`) using canonicalized values from:
     - `account_id`
     - `account_name`
     - `brokerage_name`
     - `institution` (if present on row)
   - Normalization rules:
     - case-insensitive, trim whitespace, collapse repeated spaces
     - alias-map institution names (`interactive brokers`, `ibkr`, `interactive brokers llc`)
   - Secondary: `position_source` token match.
   - Tertiary: brokerage name alias match via existing institution matcher.
   - If multiple sources still match a symbol row, emit leakage diagnostics and exclude from strict source-scoped denominator.
3. For `source="all"`, keep consolidated behavior.
4. Use scoped holdings for:
   - `current_positions`
   - coverage denominator
   - synthetic current position inference
   - synthetic current market value
5. Emit leakage diagnostics when symbol appears from multiple sources.

Acceptance:
- Synthetic symbol sets differ correctly per source and no longer include obvious cross-source contamination.
- `source_breakdown` and holdings scope fields are internally consistent.
- `ibkr_flex` holdings include IBKR symbols even when their raw `position_source` is `snaptrade`.
- Mixed-source rows no longer silently dominate source-specific coverage denominators.

### Workstream B: Soft Reliability Gate Contract
Files:
- `core/realized_performance_analysis.py`
- `core/result_objects/realized_performance.py`
- `mcp_tools/performance.py`

Changes:
1. Compute `reliable` + `reliability_reasons` in analysis engine from existing warnings/flags.
2. Thread fields through `RealizedMetadata` dataclass serialization/deserialization.
3. Expose in:
   - `to_api_response()` (`format=full`)
   - `get_agent_snapshot()` (`format=agent`)
4. Ensure `generate_performance_flags` consumes reliability fields and emits explicit warning-type flags.

Acceptance:
- Low-confidence runs retain returns but always include reliability metadata and explicit warning flags.

### Workstream C: Diagnostics Improvements for Root Cause
Files:
- `core/realized_performance_analysis.py`
- `core/result_objects/realized_performance.py`

Changes:
1. Add source-scoped counts:
   - `source_transaction_count`
   - `source_holding_count`
2. Add explicit symbol list fields for synthetic-current and leakage symbols.
3. Preserve existing fields (`synthetic_current_position_tickers`, `first_transaction_exit_details`) and ensure they are source-scoped.

Acceptance:
- `system_output_*_full.json` equivalent payloads are sufficient to explain distortions without extra runtime inspection.

## Test Plan
### Unit Tests
1. Source holdings scoping:
   - given mixed-source holdings + source-filtered transactions, verify only same-source holdings feed coverage/synthetic counts.
2. Reliability computation:
   - low coverage => `reliable=false`
   - high synthetic impact => `reliable=false`
   - healthy path => `reliable=true`

### Integration/Regression Tests
Using `tests/fixtures/performance_baseline_2025.json`:
1. Fixture policy:
   - keep existing fixture values as `pre_fix_diagnostics` reference only.
   - add `post_fix_acceptance` section with bounded assertions (not exact pinning to known-bad pre-fix metrics).
2. Source coverage sanity checks (post-fix bounds):
   - `snaptrade` source transaction count remains `0` in current environment and is marked unreliable.
   - `source_holding_count` and synthetic symbols are source-scoped (no known cross-source-only symbols appearing in wrong source synthetic set).
   - no assertion that post-fix coverage must equal pre-fix fixture percentages.
3. Snaptrade zero-transaction path:
   - `source_transaction_count == 0`, `reliable=false`, reason includes transaction-unavailable text.
4. IBKR overlap symbols:
   - ensure IBKR synthetic overlap mapping remains deterministic for `EQT/IGIC/KINS/NVDA/TKO/V`.
5. Agent contract:
   - `snapshot.data_quality.reliable` and reasons always present in realized mode.
   - `snapshot.data_quality.reliability_reason_codes` always present when `reliable=false`.

### Non-Regression Assertions
- No schema breaks for existing `format="summary"` consumers.
- Existing keys remain backward compatible; only additive fields introduced.

## Rollout Plan
1. Land Workstream A + tests.
2. Land Workstream B + tests.
3. Land Workstream C + docs updates.
4. Update `tests/fixtures/performance_baseline_2025.json`:
   - keep `pre_fix_diagnostics` values
   - add/populate `post_fix_acceptance` bounds used by CI
5. Run targeted diagnostic script to regenerate:
   - `system_output_{source}.json` and compare pre/post.
6. Review against baseline markdown and fixture deltas.

## Risks and Mitigations
- Risk: ambiguous source attribution for some holdings.
  - Mitigation: add `cross_source_holding_leakage_symbols` and conservative reliability downgrade.
- Risk: users depend on current optimistic headline numbers.
  - Mitigation: soft gate (no nulling), but warnings become explicit and machine-readable.

## Assumptions and Defaults
- Use additive API changes only (no breaking removals).
- Keep synthetic logic unchanged in Phase 1; only scope and reliability labeling change.
- Coverage thresholds reuse current config constants.
- Backfill workflow changes are deferred to Phase 2.
- `reliable` is a compatibility alias for Phase 1 confidence gating; no separate scoring model is introduced in this phase.


## Phase 2 Follow-up

Phase 1 is complete. For the remaining cash-replay distortion remediation and post-review fixes, use:
- `docs/planning/CASH_REPLAY_P2_FIX_PLAN.md`
- `docs/planning/performance-actual-2025/live_test/CASH_REPLAY_POST_P1_FINDINGS_2026-02-25.md`
