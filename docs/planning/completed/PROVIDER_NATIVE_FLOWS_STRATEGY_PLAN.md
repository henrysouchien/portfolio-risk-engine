# Provider-Native Flows Strategy Plan

**Status**: COMPLETE (diagnostics-only — provider flows used for coverage/diagnostics, inference unchanged)
**Date**: 2026-02-16
**Key files**: `providers/flows/`, `settings.py` (feature flags), `core/realized_performance_analysis.py`

---

## Goal

Use provider-reported cash flows as the primary source for NAV-adjusted return calculations, with inference only as a fallback when provider flow coverage is missing or unreliable.

---

## Problem Summary

Current flow-adjusted return logic infers external flows from normalized trade and income events. This can miss timing, mask real withdrawals, and distort NAV-adjusted returns when providers already expose explicit cash flow events.

Primary current flow path:
- `core/realized_performance_analysis.py` -> `derive_cash_and_external_flows()`

---

## Strategy Decisions

1. Provider-reported flows are the default source of truth.
2. Inferred flows remain available as fallback only.
3. External flow sign convention is standardized:
   - Positive = contribution/deposit
   - Negative = withdrawal/disbursement
4. Trade cash legs are not external flows.
5. Internal account-to-account transfers should net out at portfolio scope where both sides are present.

---

## Canonical Flow Event Model

Provider flow events should normalize to a shared schema:

```python
{
  "date": datetime,
  "amount": float,             # signed (+inflow, -outflow)
  "currency": str,             # ISO code, default USD only when missing
  "flow_type": str,            # contribution|withdrawal|fee|transfer|other
  "is_external_flow": bool,    # true for capital flows, false for fee/internal cash-only events
  "provider": str,             # plaid|snaptrade|schwab|ibkr_flex
  "institution": str,
  "account_id": str,
  "transaction_id": str,
  "confidence": str,           # provider_reported|inferred
}
```

Notes:
- Keep this separate from trade and income normalization.
- Preserve raw provider hints where useful (`type`, `subtype`, original labels).
- Cash replay includes fee/cash-impact events; external-flow math includes only `is_external_flow=true`.

---

## Provider Coverage (Research Summary)

### Schwab
- Transaction families include explicit cash movement types (`ACH_*`, `WIRE_*`, `CASH_*`, `JOURNAL`) in addition to `TRADE` and `DIVIDEND_OR_INTEREST`.
- Best candidate for first implementation due to direct event typing and current bug impact.

### Plaid
- Investment transactions include non-trade types/subtypes that represent cash movement (`cash`, `transfer`, `contribution`, `withdrawal`, etc.).
- Requires careful sign normalization from Plaid amount conventions.

### SnapTrade
- Account activities include flow-like types (`CONTRIBUTION`, `WITHDRAWAL`, `TRANSFER`, `FEE`) along with trade/income.
- Some flow events may not include a security symbol.

### IBKR Flex
- Current pipeline ingests only `Trade` rows.
- Provider supports additional statement sections with cash movement data, but they are not yet ingested in this code path.

---

## Integration Architecture (Planning)

1. Add a dedicated provider flow extraction stage (parallel to trade/income normalization).
2. Build a combined, normalized flow event list across providers.
3. Update NAV flow engine to consume:
   - Provider flows first
   - Inferred flows only for uncovered windows/accounts/providers
   - Inference explicitly excluded from provider-authoritative slices to prevent double counting
4. Introduce flow coverage/quality checks:
   - Missing periods
   - Suspected partial provider payloads
   - Potential duplicate flow events

---

## Rollout Sequence

1. Phase 1: Schwab provider-reported flows
2. Phase 2: SnapTrade + Plaid provider-reported flows
3. Phase 3: IBKR Flex cash flow ingestion (beyond current `Trade` extraction)
4. Keep a temporary feature flag for old inference-only behavior during rollout validation

---

## Validation Plan

1. Provider-specific fixtures for deposit/withdrawal/transfer/fee scenarios
2. Regression tests on:
   - Monthly NAV
   - Modified Dietz and flow-adjusted return series
   - Net flow totals by month
3. Shadow comparison:
   - Existing inferred-only path vs provider-first path
   - Alert thresholds for material return deltas
4. Include rollout diagnostics in realized output:
   - `flow_source_breakdown`
   - `provider_flow_coverage`
   - `flow_fallback_reasons`

---

## Out of Scope (This Strategy Doc)

- No code changes yet
- No schema migration yet
- No breaking API contract changes yet (additive metadata fields are allowed for diagnostics)

Implementation detail doc:
- `docs/planning/PROVIDER_NATIVE_FLOWS_IMPLEMENTATION_PLAN.md`
