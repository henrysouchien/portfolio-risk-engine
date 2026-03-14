# Provider-Native Flows Cutover Plan

Date: 2026-02-17
Status: Draft
Owner: Backend Platform (Provider Flows)

## Objective

Promote provider-authoritative flow events from diagnostics-only into live cash/external-flow composition in `core/realized_performance_analysis.py` once rollout gates are met.

## Preconditions

1. `docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md` is implemented and validated.
2. Shadow diagnostics for `REALIZED_PROVIDER_FLOW_SOURCES=schwab,plaid,snaptrade,ibkr_flex` are stable.
3. No unresolved high-severity issues in provider-flow authority metadata (`missing_fetch_metadata`, `partial_or_truncated`, `fetch_error`) for production accounts.

## Cutover Changes

1. Remove diagnostics-only hotfix in `_compose_cash_and_external_flows()` so authoritative provider flows are applied.
2. Keep feature-flag gating:
- `REALIZED_USE_PROVIDER_FLOWS=true`
- `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true`
- source scoping via `REALIZED_PROVIDER_FLOW_SOURCES`
3. Apply authoritative provider events to:
- cash snapshots (including fees)
- external-flow series (`is_external_flow=true` only)
4. Keep non-authoritative slices inference-backed.

## Validation Gates

1. Unit/integration:
- `pytest tests/core/test_realized_performance_analysis.py -k provider_flow -q`
- `pytest tests/providers/test_transaction_providers.py -q`
- `pytest tests/providers/flows -q`
2. Reconciliation:
- No double-counting against trade cash legs on sampled multi-provider portfolios.
- `provider_authoritative_applied > 0` where expected and fallback reasons remain explicit for non-authoritative slices.
3. Drift checks:
- Compare realized return deltas vs baseline across shadow accounts; investigate unexplained outliers before broad enablement.

## Rollout Sequence

1. Stage 1: Enable cutover for internal shadow users only.
2. Stage 2: Enable for a limited production cohort with daily diagnostics review.
3. Stage 3: Expand gradually to all users if deltas and diagnostics stay within expected bounds.

## Rollback

1. Immediate: set `REALIZED_USE_PROVIDER_FLOWS=false`.
2. Partial: keep provider flows enabled but remove specific providers from `REALIZED_PROVIDER_FLOW_SOURCES`.
3. Preserve diagnostics output for postmortem and remediation.
