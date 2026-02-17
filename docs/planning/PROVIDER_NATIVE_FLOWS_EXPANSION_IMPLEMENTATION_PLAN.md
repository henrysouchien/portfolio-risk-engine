# Provider-Native Flows Expansion Implementation Plan

Date: 2026-02-17  
Status: Implemented (2026-02-17)  
Scope Type: Incremental rollout (provider-by-provider, feature-flagged)

## Related Documents

- `docs/planning/TODO.md`
- `docs/planning/completed/PROVIDER_NATIVE_FLOWS_STRATEGY_PLAN.md`
- `docs/planning/completed/PROVIDER_NATIVE_FLOWS_IMPLEMENTATION_PLAN.md`

## Problem Statement

Provider-native flow infrastructure exists, but production flow authority is effectively Schwab-only:

1. Plaid and SnapTrade flow events are extracted, but provider-level fetch metadata is missing for authoritative coverage gating.
2. IBKR Flex flow extraction is intentionally stubbed and currently returns no provider-native flow events.
3. IBKR ingestion only parses `Trade` rows, so deposits/withdrawals/fees from non-Trade sections are not available to the flow engine.

Also, current realized composition keeps provider flows diagnostics-only via a hotfix path in `core/realized_performance_analysis.py` (`provider_authoritative_applied` forced to `0`).

Result: realized flow diagnostics are present, but non-Schwab providers cannot reliably participate in coverage-aware provider flow diagnostics, and no provider can yet apply authoritative flows to cash/external-flow composition in production.

## Goals

1. Make Plaid and SnapTrade provider flow slices coverage-aware and eligible for authoritative gating decisions (diagnostics path).
2. Add IBKR Flex provider-native cash flow extraction beyond `Trade` rows.
3. Preserve existing realized-performance API contracts and fallback behavior.
4. Keep rollout controlled via existing feature flags in `settings.py`.
5. Keep current diagnostics-only composition behavior unchanged in this plan; define a follow-on cutover for authoritative flow application.

## Non-Goals

1. Reworking FIFO trade matching or changing trade/income normalization contracts.
2. Modifying Schwab flow extraction logic (already active).
3. Large schema/database changes.
4. Enabling provider-authoritative flows by default for all providers in one step.
5. Removing the diagnostics-only hotfix in `core/realized_performance_analysis.py` as part of this implementation milestone.

## Current State Summary

1. `providers/flows/plaid.py` and `providers/flows/snaptrade.py` map provider rows to normalized flow events.
2. `providers/flows/ibkr_flex.py` is a phase-1 stub that returns `[]`.
3. `ibkr/flex.py` currently extracts and normalizes `Trade` rows only.
4. `trading_analysis/data_fetcher.py` supports side-channel fetch metadata (`_last_fetch_metadata`) but Plaid/SnapTrade/IBKR transaction providers do not emit metadata today.
5. `settings.py` defaults `REALIZED_PROVIDER_FLOW_SOURCES` to `"schwab"`.
6. `_compose_cash_and_external_flows()` currently tracks provider authority availability but intentionally does not apply provider flows to cash/external-flow math.
7. IBKR Flex fetch path currently fail-opens to empty payload on credential/download/parse failures; metadata integration must distinguish success from failure (do not infer exhaustion from empty payload).

## Target Architecture

1. Plaid and SnapTrade transaction providers emit per-slice `FetchMetadata` side-channel rows.
2. IBKR Flex ingestion exposes both:
- existing normalized trades (`ibkr_flex_trades`)
- normalized cash-flow source rows for flow extraction (`ibkr_flex_cash_rows`)
3. IBKR flow extractor maps cash rows into canonical provider flow events with conservative classification.
4. Coverage gating in `core/realized_performance_analysis.py` works unchanged, with new provider metadata feeding existing authority logic and diagnostics (`provider_authoritative_available`, `flow_fallback_reasons`).
5. IBKR API compatibility is preserved: existing `fetch_ibkr_flex_trades(...) -> list[dict]` contract remains unchanged.
6. New IBKR cash-row access is additive (new helper or parallel extraction path), not a return-type mutation of existing functions.
7. Metadata slice granularity is account-scoped for all providers. Plaid metadata must be emitted per account within each token fetch loop (not token-aggregate rows).

## Non-Negotiable Decisions

1. **Plaid metadata granularity:** one metadata row per account slice inside each token loop.
2. **IBKR runtime dependency:** implement and validate against `ib_async.FlexReport` behavior (tag-based, case-sensitive extraction), not ibflex runtime assumptions.
3. **IBKR metadata trust model:** `pagination_exhausted=True` only when fetch succeeded and exhaustion is proven; failed/partial fetches must set `partial_data=True` and/or `fetch_error`.
4. **IBKR non-Trade section precedence:** `CashTransaction` primary; `Transfer` (`cashTransfer=true`) secondary fallback with explicit overlap dedup policy.

## Migration Strategy

Roll out in phases with explicit validation gates and rollback points. Do not expand provider-flow source flags until each provider phase is validated. Keep provider-flow application diagnostics-only in this milestone.

## Phase 0: Baseline and Discovery

### Deliverables

1. Baseline test snapshot for current provider-flow behavior.
2. Confirmed list of IBKR Flex section names/fields available in real sample report(s) for cash movement rows.
3. Confirmed IBKR `extract(topic)` tag names used by `ib_async.FlexReport` against real sample report(s), including exact case.
4. Written IBKR non-Trade precedence/dedup policy (`CashTransaction` vs `Transfer`).

### Tasks

1. Run and capture baseline:
- `pytest tests/providers/flows/test_plaid_flows.py -q`
- `pytest tests/providers/flows/test_snaptrade_flows.py -q`
- `pytest tests/providers/flows/test_extractor.py -q`
- `pytest tests/core/test_realized_performance_analysis.py -k provider_flow -q`
2. Add a small diagnostic helper test fixture or script (test-only) to inspect IBKR Flex report section availability from local sample XML.
3. Validate exact section tag names for `ib_async.FlexReport.extract(...)` using sample report XML.
4. Freeze a field map for IBKR cash sections (candidate date/amount/type/account/currency/id fields).
5. Freeze section precedence/dedup policy:
- `CashTransaction` authoritative source for cash events
- `Transfer` (`cashTransfer=true`) only fills gaps when no matching `CashTransaction` event exists
- define overlap match key for dedup (provider + institution + account identity + normalized event date + currency + absolute amount + normalized class)

### Validation Gate

1. Baseline tests pass unchanged.
2. IBKR field map documented in this plan (or a linked note) before parser implementation.
3. IBKR tag-name validation and section precedence/dedup policy documented before Phase 3.

### Rollback

1. Remove discovery artifacts if they introduce noise and keep behavior unchanged.

## Phase 1: Plaid and SnapTrade FetchMetadata

### Deliverables

1. `PlaidTransactionProvider` emits `_last_fetch_metadata` entries per account/institution slice.
2. `SnapTradeTransactionProvider` emits `_last_fetch_metadata` entries per account/brokerage slice.
3. Metadata includes required authority fields:
- `provider`, `institution`, `account_id`, `account_name`
- `fetch_window_start`, `fetch_window_end`
- `payload_coverage_start`, `payload_coverage_end`
- `pagination_exhausted`, `partial_data`, `fetch_error`, `row_count`
- optional `unmapped_row_count` (default `0`) for authority diagnostics parity

### Tasks

1. Implement side-channel metadata construction in:
- `providers/plaid_transactions.py`
- `providers/snaptrade_transactions.py`
2. Preserve existing transaction payload contract (no breaking changes).
3. Ensure `_last_fetch_metadata` reset semantics at call start to avoid stale metadata reuse.
4. Plaid metadata emission rule:
- emit one metadata row per account slice inside each token fetch loop (not one row per token aggregate).
5. Plaid empty-page edge-case rule:
- if an empty page occurs before proving `offset >= total_investment_transactions`, set `pagination_exhausted=False` and `partial_data=True`.
6. SnapTrade coverage-date rule:
- compute coverage bounds from extractor-equivalent date fallback: `trade_date` OR `settlement_date` OR `date`.
7. SnapTrade empty-page edge-case rule:
- if an empty page occurs before proving `offset >= total`, set `pagination_exhausted=False` and `partial_data=True`.
8. Use conservative metadata rules for currently available observability:
- set `pagination_exhausted=True` only when provider fetch loop deterministically consumed all pages for the requested window
- when certainty is unavailable, set `pagination_exhausted=False` so slice remains non-authoritative
9. Add focused unit tests in `tests/providers/test_transaction_providers.py` for Plaid/SnapTrade metadata emission.

### Validation Gate

1. `pytest tests/providers/test_transaction_providers.py -q`
2. Existing flow extractor tests remain green.
3. `fetch_transactions_for_source(..., source="plaid|snaptrade")` returns metadata via `FetchResult.fetch_metadata`.
4. New tests cover:
- Plaid per-account metadata rows inside token loops
- Plaid empty-page-before-total semantics (`partial_data=True`, `pagination_exhausted=False`)
- SnapTrade coverage-date fallback (`trade_date` / `settlement_date` / `date`)
- SnapTrade empty-page-before-total semantics (`partial_data=True`, `pagination_exhausted=False`)

### Rollback

1. Disable metadata emission for the provider if authority behavior regresses; keep event extraction active.

## Phase 2: Plaid and SnapTrade Authority Eligibility (Diagnostics-Only)

### Deliverables

1. Realized-performance provider-flow tests proving authoritative/non-authoritative coverage decisions for Plaid and SnapTrade slices.
2. Controlled runtime activation path for:
- `REALIZED_PROVIDER_FLOW_SOURCES=schwab,plaid,snaptrade`

### Tasks

1. Add integration tests in `tests/core/test_realized_performance_analysis.py` that:
- inject provider flow events + metadata
- verify authoritative availability counting and fallback reasons
2. Keep default settings unchanged in code (`schwab` only); activation is environment-driven.
3. Add short operational note to TODO or release notes on recommended flag sequence.
4. Explicitly verify diagnostics-only behavior remains unchanged:
- `provider_authoritative_applied == 0`

### Validation Gate

1. `pytest tests/core/test_realized_performance_analysis.py -k provider_flow -q`
2. No regression in generalized realized-performance tests.

### Rollback

1. Remove `plaid,snaptrade` from `REALIZED_PROVIDER_FLOW_SOURCES`.

## Phase 3: IBKR Flex Cash Section Ingestion

### Deliverables

1. IBKR fetch path returns normalized cash-flow source rows in addition to trades.
2. IBKR flow extractor maps cash rows into canonical provider flow events.
3. IBKR non-Trade section precedence/dedup is implemented and test-covered.

### Tasks

1. Extend `ibkr/flex.py` with a new extractor for non-Trade sections (final section names from Phase 0 discovery), producing a normalized row shape for flow mapping.
   Keep `fetch_ibkr_flex_trades(...)` return type unchanged.
   Use `ib_async.FlexReport.extract(...)` with Phase 0 validated, case-sensitive tag names.
2. Extend `providers/ibkr_transactions.py` to return:
- `ibkr_flex_trades` (existing)
- `ibkr_flex_cash_rows` (new)
3. Extend payload defaults/merge paths in `trading_analysis/data_fetcher.py` for new key.
4. Update `providers/flows/extractor.py` and `providers/flows/ibkr_flex.py` to consume and map `ibkr_flex_cash_rows`.
5. Preserve slice-identity fields end-to-end for IBKR cash rows/events so authority keying remains account-scoped:
- `provider` = `ibkr_flex`
- `institution` (normalized canonical value, e.g., `ibkr`)
- `account_id` (when available from Flex row/account context)
- `account_name` (when available)
- `provider_account_ref` (when available, stable account reference)
6. Preserve event currency end-to-end:
- map provider currency from IBKR cash rows to normalized flow events without silent USD replacement when a valid currency is present
- only fall back to USD when provider currency is missing/invalid
7. Keep conservative classification:
- contribution/withdrawal only with explicit evidence
- ambiguous transfers remain `transfer` with `is_external_flow=false`
- fees mapped to `flow_type=fee`, `is_external_flow=false`
8. Implement section precedence and overlap handling:
- parse `CashTransaction` first (primary source)
- parse `Transfer` rows with `cashTransfer=true` second (secondary source)
- skip secondary rows that overlap a primary row using the Phase 0 match key policy
9. Protect ID stability for dedup keys:
- avoid numeric coercion for identifier fields (parse IDs as strings, or cast explicitly to string before keying)
- parse numeric amount fields explicitly and separately
10. Add warning/diagnostics behavior:
- emit warning when expected cash sections are absent from a successfully downloaded Flex report
- do not treat “section absent” as fetch success for authority unless semantics are explicitly complete

### Validation Gate

1. New IBKR flow-unit tests pass:
- `tests/providers/flows/test_ibkr_flex_flows.py`
2. Existing IBKR trade normalization tests remain green.
3. `extract_provider_flow_events()` includes IBKR events when cash rows are present.
4. New propagation test verifies `ibkr_flex_cash_rows` survives:
- provider payload -> `fetch_all_transactions()`/`fetch_transactions_for_source()` -> `FetchResult.payload` -> `extract_provider_flow_events()`
5. New identity-field tests verify IBKR flow events retain slice-key fields (`institution`, `account_id`/`provider_account_ref`/`account_name`) needed by authority logic.
6. New currency tests verify IBKR cash-row currency propagates to flow events (including at least one non-USD case) and only defaults to USD when currency is missing/invalid.
7. IBKR compatibility/caller contracts remain green:
- `pytest tests/ibkr/test_compat.py -q`
- `pytest tests/providers/test_provider_switching.py -q`
- any direct unit tests that assert `fetch_ibkr_flex_trades(...) -> list[dict]` behavior
8. New tests cover:
- precedence/dedup between `CashTransaction` and `Transfer(cashTransfer=true)`
- ID stability against numeric coercion for identifier fields
- warning path when cash sections are absent

### Rollback

1. Feature-disable IBKR cash row usage by returning empty `ibkr_flex_cash_rows` while keeping trade path intact.

## Phase 4: IBKR Metadata and Authority Integration

### Deliverables

1. IBKR transaction provider emits `FetchMetadata` rows compatible with authority gating.
2. End-to-end realized-performance behavior validated with IBKR in provider-flow sources.
3. IBKR metadata clearly distinguishes success vs failure/partial states.

### Tasks

1. Add `_last_fetch_metadata` generation in `providers/ibkr_transactions.py` using available request window and payload coverage fields.
   Metadata must be emitted per authority slice key (`provider` + `institution` + `account_id`/`provider_account_ref`/`account_name`), not as provider-level aggregate rows.
   Success/failure semantics:
   - success: `fetch_error=None`, `partial_data=False`, `pagination_exhausted=True` only when completion is proven
   - partial/unknown: `partial_data=True`, `pagination_exhausted=False`
   - failure: non-empty `fetch_error`, `partial_data=True`, `pagination_exhausted=False`, `row_count=0`
2. For pre-slice hard failures (e.g., credentials/download/parse before account partition), emit metadata with failure semantics and null account identity fields; do not mark exhausted.
3. Add provider tests for IBKR metadata contract.
4. Add realized-performance integration tests with:
- authoritative-eligible IBKR slices
- coverage failure fallback
5. Enable staged runtime source set:
- `REALIZED_PROVIDER_FLOW_SOURCES=schwab,plaid,snaptrade,ibkr_flex`

### Validation Gate

1. `pytest tests/providers/test_transaction_providers.py -q`
2. `pytest tests/core/test_realized_performance_analysis.py -k provider_flow -q`
3. Shadow-run comparisons show expected diagnostics without large unexplained return deltas.
4. `provider_authoritative_applied` remains `0` (hotfix unchanged).
5. New metadata tests verify per-slice IBKR metadata rows align with IBKR flow-event slice identities so authority does not degrade to `missing_fetch_metadata` for account-partitioned events.
6. New metadata tests verify failed/partial IBKR fetches never report `pagination_exhausted=True` with ambiguous/empty payloads.
7. New metadata tests verify pre-slice hard failures emit null account identity fields with non-authoritative failure semantics.

### Rollback

1. Remove `ibkr_flex` from `REALIZED_PROVIDER_FLOW_SOURCES`.

## Testing Strategy

1. Unit tests:
- provider transaction metadata emission
- provider flow mapping logic for each provider
2. Integration tests:
- realized-performance provider-flow authority and fallback behavior
3. Regression tests:
- existing trading analysis and provider routing tests

## Rollout Order

1. Ship Phase 1 and Phase 2 first (Plaid/SnapTrade metadata + authority eligibility diagnostics).
2. Ship Phase 3 and Phase 4 second (IBKR cash ingestion + authority eligibility diagnostics).
3. Keep default source list unchanged until each phase validates in shadow mode.

## Follow-On Cutover (Separate Plan)

After this plan completes, create a dedicated cutover plan to remove diagnostics-only behavior and apply authoritative provider flows in cash/external-flow composition. That cutover should include:

1. Explicit implementation changes in `_compose_cash_and_external_flows()` to apply authoritative provider flow events.
2. Guardrails/feature flag for controlled rollout.
3. Reconciliation tests proving no double-counting against trade cash legs.

Trigger and timing:

1. Trigger immediately when Phase 4 validation gate passes.
2. Create `docs/planning/PROVIDER_NATIVE_FLOWS_CUTOVER_PLAN.md` within 1 business day of Phase 4 completion.
3. Add a `TODO.md` item pointing to the cutover plan in the same PR/commit that marks Phase 4 complete.

## Risks and Mitigations

1. IBKR section/field drift risk:
- Mitigation: discovery-first phase and conservative parser with explicit unknown-row logging.
2. False-positive external flow classification:
- Mitigation: fail-closed defaults for ambiguous transfer rows.
3. Metadata gaps causing unexpected fallback:
- Mitigation: dedicated provider metadata tests and serialized diagnostics verification.
4. IBKR extraction tag mismatch risk (case-sensitive):
- Mitigation: Phase 0 real-report tag validation and tag-name tests.
5. ID coercion affecting dedup:
- Mitigation: string-preserving ID normalization + explicit amount parsing.

## Definition of Done

1. Plaid, SnapTrade, and IBKR Flex have provider-native flow event extraction plus fetch metadata.
2. Realized-performance provider-flow authority eligibility diagnostics work for all four providers under `REALIZED_PROVIDER_FLOW_SOURCES`.
3. Fallback diagnostics remain explicit and test-covered.
4. `docs/planning/TODO.md` points to this active plan as the implementation source of truth.
5. A follow-on cutover plan file exists (`docs/planning/PROVIDER_NATIVE_FLOWS_CUTOVER_PLAN.md`) with explicit owner and rollout gate criteria.
