# Provider-Native Flows Implementation Plan

**Status**: COMPLETE (diagnostics-only scope — see strategy plan)
**Date**: 2026-02-16
**Key files**: `providers/flows/{schwab,plaid,snaptrade,ibkr_flex,extractor,common}.py`, `core/realized_performance_analysis.py`
**Depends on**:
- `docs/planning/PROVIDER_NATIVE_FLOWS_STRATEGY_PLAN.md`
- `docs/planning/SCHWAB_NORMALIZER_FIX_PLAN.md`

---

## Objective

Implement provider-first external cash flow handling for NAV-adjusted realized returns while preserving current behavior as fallback.

Primary target:
- `core/realized_performance_analysis.py`

---

## Success Criteria

1. NAV flow engine uses provider-reported flows when available.
2. Inference still works for providers/windows without usable flow data.
3. No regression in existing trade/income/FIFO matching behavior.
4. No schema/database migrations required.
5. Rollback is one flag change.
6. Fees reduce performance but are **not** treated as external capital flows.
7. Fee events on authoritative provider slices are applied to cash/NAV replay (performance drag), while excluded from `external_flows`.
8. Realized output includes explicit provider-vs-inferred flow diagnostics for rollout validation.
9. Provider-first flow composition is applied consistently to both NAV tracks:
   - synthetic-enhanced path
   - observed-only path
10. `net_contributions` semantics are explicit and backward compatible.

---

## Key Design Choice (Low-Risk Path)

Do **not** change `TransactionNormalizer` contract (`trades, income, fifo`).

Why:
- `TradingAnalyzer` enforces trade/FIFO index alignment.
- Widening that contract would ripple across every normalizer and analyzer path.

Instead:
1. Keep transaction normalization unchanged.
2. Add a parallel provider-flow extraction path from raw payloads.
3. Merge provider flows into realized performance cash/flow computation.

---

## Canonical Flow Schema

Create a normalized flow event format:

```python
{
  "date": datetime,
  "amount": float,             # signed: + contribution, - withdrawal
  "timestamp": datetime,       # optional provider event timestamp (naive UTC, more granular than date)
  "event_day_utc": date,       # date-only (UTC) for day-bucketing in dedup/netting
  "currency": str,             # ISO-3
  "flow_type": str,            # contribution|withdrawal|fee|transfer|other
  "is_external_flow": bool,    # true for contribution/withdrawal, false for fee/other
  "provider": str,             # schwab|plaid|snaptrade|ibkr_flex
  "institution": str,
  "account_id": str,
  "account_name": str,         # optional display name for fallback keying when account_id absent
  "provider_account_ref": str, # optional stable provider account key when account_id is absent
  "transaction_id": str,
  "confidence": str,           # provider_reported|inferred
  "raw_type": str,
  "raw_subtype": str,
  "raw_description": str,      # optional provider memo/description
  "provider_row_fingerprint": str,  # stable hash from raw provider row content for dedup fallback
  "transfer_cash_confirmed": bool,  # transfer represents actual cash movement
}
```

External-flow classification policy:
- `contribution` / `withdrawal` => `is_external_flow=true`
- `fee` => `is_external_flow=false` (performance drag, not capital movement)
- `transfer` => conditional (see transfer handling policy)

Cash replay policy:
- Provider flow events that change cash (including `fee`) are reflected in cash snapshots only for authoritative slices.
- Provider rows from non-authoritative slices are diagnostics-only and do not alter cash replay.
- Only `is_external_flow=true` events feed `external_flows` used for Modified Dietz net-flow adjustment.
- For `flow_type=transfer`, `is_external_flow=true` only when `transfer_cash_confirmed=true`.

## Event Identity and Dedup Policy

1. Deduplicate normalized provider flow events before coverage checks, transfer netting, cash replay, and external-flow aggregation.
2. Primary dedup key:
   - `(provider, canonical_account_identity, transaction_id)` when `transaction_id` is present.
   - **Canonical account identity** (Codex R7#3): Use the same `build_slice_key()` account resolver for dedup that slice-keying uses: `account_id -> provider_account_ref -> account_name -> "unknown"`. This prevents false dedup of same `transaction_id` across different accounts when account_id is missing but account_name differs.
3. Fallback dedup fingerprint when `transaction_id` is missing:
   - `(provider, canonical_account_identity, timestamp_or_date, normalized_amount, currency, raw_type, raw_subtype, raw_description_or_empty, provider_row_fingerprint_or_empty)`.
   - Do not dedup on coarse day-level keys alone; fallback must require near-exact row identity.
   - Fail-open guard: if both `provider_row_fingerprint` and `raw_description` are missing and only coarse identity is available, skip dedup for those rows.
4. On duplicate groups, keep first event by deterministic sort key -- sort by `(provider, timestamp or date, transaction_id or empty, account_id, fingerprint)` before dedup, and log the winning key. Do not rely on ingestion order which may vary across re-fetches/cache merges (Codex #12).
5. Dedup diagnostics must include duplicate counts by source/provider and by slice key.

---

## Provider Mapping Rules (Initial)

### Schwab

**Status gating** (Codex #5): All Schwab flow extractors must filter on `status` field before mapping. Only process rows with `status=VALID` (or missing status, for backward compat). Skip `PENDING`, `CANCELED`, `INVALID` rows with a debug log.

- Use `type` families from Schwab transactions:
  - inflow: `ACH_RECEIPT`, `CASH_RECEIPT`, `WIRE_IN`
  - outflow: `ACH_DISBURSEMENT`, `CASH_DISBURSEMENT`, `WIRE_OUT`
  - conditional: `ELECTRONIC_FUND`, `JOURNAL` (see conservative rules below)
- Exclude from external flow:
  - `TRADE`, `MEMORANDUM`, `MARGIN_CALL`, `CORPORATE_ACTION`
  - `MONEY_MARKET`, `SAVINGS` (cash sweep mechanics; do not treat as external capital by default)
  - `RECEIVE_AND_DELIVER` (asset transfer, not cash external flow)

Schwab type policy must be explicit for all currently documented transaction families:
- `TRADE`: ignore for external flow
- `DIVIDEND_OR_INTEREST`: ignore for external flow **except** negative/fee-like interest rows (margin interest, debit interest). Use the shared resolved subtype pattern (`transactionSubType or activityType`, Codex R2#4) to check for `INTEREST`/`CREDIT_INTEREST` with negative `netAmount` -- emit as `flow_type=fee`, `is_external_flow=false`. These reduce cash/NAV in authoritative cash replay but do not count as external capital flows (Codex R1#4).
- `ACH_RECEIPT`: contribution
- `ACH_DISBURSEMENT`: withdrawal
- `CASH_RECEIPT`: contribution
- `CASH_DISBURSEMENT`: withdrawal
- `WIRE_IN`: contribution
- `WIRE_OUT`: withdrawal
- `ELECTRONIC_FUND`: default to `flow_type=transfer`, `is_external_flow=false`. Only promote to contribution/withdrawal when explicit external-cash evidence exists (e.g., description contains "ACH", "WIRE", "DEPOSIT", "WITHDRAWAL"). Many `ELECTRONIC_FUND` rows are internal sweeps/transfers that would be misclassified by sign alone (Codex #9).
- `JOURNAL`: default to `flow_type=transfer`, `is_external_flow=false`. Only promote to external flow when description/subtype provides explicit external-cash evidence. Internal sweeps, rewards, and margin transfers must not be classified as contributions/withdrawals (Codex #9).
- `RECEIVE_AND_DELIVER`: transfer candidate (non-cash by default, requires explicit cash evidence)
- `MEMORANDUM`: ignore
- `MARGIN_CALL`: ignore
- `MONEY_MARKET`: ignore
- `SAVINGS`: ignore
- `CORPORATE_ACTION`: ignore

`transfer_cash_confirmed` rules (Schwab):
- `true` only when transfer-like event has explicit cash semantics (cash amount + cash movement type/sign).
- `false` for asset-transfer records without clear cash movement evidence.

### Plaid
- Use `type` + `subtype`:
  - inflow candidates: `contribution`, `deposit`
  - outflow candidates: `withdrawal`
  - conditional by sign: `cash`, `transfer`
  - `fee` -> `flow_type=fee`, `is_external_flow=false`
- Normalize Plaid investment sign convention to canonical sign.

`transfer_cash_confirmed` rules (Plaid):
- `true` for cash transfer/contribution/withdrawal subtypes with monetary amount and no security quantity dependency.
- `false` when record indicates security transfer/position movement without clear cash movement.

### SnapTrade
- Use activity `type`:
  - inflow: `CONTRIBUTION`
  - outflow: `WITHDRAWAL`
  - conditional/transfer: `TRANSFER` (signed by amount if available)
- `FEE` -> `flow_type=fee`, `is_external_flow=false`
- Exclude trade/income types from external flow list.

`transfer_cash_confirmed` rules (SnapTrade):
- `true` when activity `type=TRANSFER` includes clear cash amount semantics.
- `false` when transfer appears to be asset movement or lacks sufficient cash-direction evidence.

### IBKR Flex (Phase 1 behavior)
- Keep unsupported for provider-first flow extraction in first release.
- Return no provider-reported flows; inference remains active for `ibkr_flex`.

---

## Transfer Handling Policy

1. Keep transfer events as `flow_type=transfer` in normalized flow list.
2. Net transfers only when all conditions match and pairing is one-to-one:
   - same provider
   - same currency
   - opposite signs
   - same normalized amount (with tolerance)
   - different account identities (`account_id_or_provider_account_ref`)
   - within same normalized UTC calendar day (phase 1); no sub-day fuzzy window in phase 1
   - unique counterpart after filtering (no many-to-many bucket)
   - Strengthen pairing with available linkage fields: provider refs, memo/description patterns, known account relationships. Use these as tie-breakers when multiple candidates match on amount/date. Conservative no-net fallback when tie-breaking is insufficient (Codex #11).
3. Do not net across providers.
4. If confidence is low (missing account identity or ambiguous metadata), keep as unmatched and warn.
5. Residual unmatched transfer amount counts as external flow **only** when `transfer_cash_confirmed=true`.
6. Non-cash transfer candidates (e.g., asset transfer records) remain non-external and are excluded from external flow totals.
7. Emit warning when transfer matching is ambiguous.
8. Prefer provider linkage identifiers when available (future enhancement).
9. If a transfer bucket is ambiguous (many-to-many candidates), do not net any events in that bucket; keep all unmatched and emit warning.

---

## Coverage Gating Rules

Provider-reported flows should only be authoritative when coverage appears sufficient.

Coverage terminology:
- "Eligible provider flow event" means a normalized provider event that passes mapping validation and dedup for the slice.
- Eligibility includes cash-impact non-external events (for example `fee`) and external-flow events.
- External-flow math still uses only `is_external_flow=true`; eligibility is a coverage concept, not an external-flow inclusion rule.

### Fetch Metadata (Codex #1)

Current fetch path (`trading_analysis/data_fetcher.py`) returns only raw lists with no per-slice fetch metadata. Coverage gating requires knowing whether the fetch completed successfully and without truncation.

Add a `FetchMetadata` structure to the provider flow extraction return:
```python
{
  "provider": str,
  "institution": str | None,           # institution name for routing filter alignment (Codex R8#1)
  "account_id": str | None,
  "account_name": str | None,          # for fallback keying
  "provider_account_ref": str | None,  # stable key when account_id absent
  "fetch_window_start": datetime | None,   # API request window start
  "fetch_window_end": datetime | None,     # API request window end
  "payload_coverage_start": datetime | None,  # min event date in returned data (Codex R7#4)
  "payload_coverage_end": datetime | None,    # max event date in returned data
  "pagination_exhausted": bool, # true if all pages fetched
  "partial_data": bool,         # true if API returned partial/truncated response
  "fetch_error": str | None,    # error message if fetch failed
  "row_count": int,             # total rows returned before filtering
}
```

**FetchMetadata ownership** (Codex R5#4): The fetcher layer (`data_fetcher.py`) is the sole owner of `FetchMetadata` construction -- it has access to pagination state, error conditions, and fetch windows. Provider flow extractors (`providers/flows/*.py`) receive raw rows and return only normalized flow events (`list[dict]`). They do NOT produce `FetchMetadata`. The orchestrator (`providers/flows/extractor.py`) receives both events (from extractors) and metadata (from the fetcher layer via `FetchResult`), then passes both to coverage gating.

**Fetch-layer payload contract changes** (Codex R2#3, R4#1): The current `_merge_payloads()` in `data_fetcher.py` drops unknown keys (`if key not in base: continue`). Metadata must be collected BEFORE the merge step.

**Concrete transport contract**: Each provider's `fetch_transactions()` continues to return a payload dict (no provider-level changes). Metadata is collected in the fetcher layer:
1. In `fetch_all_transactions()`, after each provider fetch and before `_merge_payloads()`, the fetcher builds `FetchMetadata` from provider-specific signals:
   - Schwab: `providers/schwab_transactions.py` already tracks per-account fetch windows and errors internally. Add a `_last_fetch_metadata` attribute (or return side-channel) that the fetcher reads after `fetch_transactions()`. **Reset semantics** (Codex R8#5): Provider must clear/reset `_last_fetch_metadata` to `None` at the start of each `fetch_transactions()` call. The fetcher must treat `None` metadata as "unavailable for this call" (not stale from prior calls). This prevents stale metadata from contaminating authority checks when provider instances are reused across calls (custom registries, tests).
   - Other providers: return empty metadata initially (Phase 1).
2. Metadata is accumulated in a `fetch_metadata_list` alongside the payload merge loop.
3. **Fetch error resilience** (Codex R5#1, R6#2): Error isolation at TWO levels:
   - **Provider level**: `fetch_all_transactions()` catches per-provider exceptions, emits `FetchMetadata` with `fetch_error`, continues to next provider. Hard-fail only when NO provider returns usable data.
   - **Account level** (Codex R6#2): `SchwabTransactionProvider.fetch_transactions()` currently loops accounts/windows and raises on any failure, losing all Schwab data. Require per-account error isolation: catch account-level exceptions, continue fetching other accounts, return partial payload, and emit per-account `FetchMetadata` entries with errors. This ensures one Schwab account failure doesn't drop all Schwab data. The `_last_fetch_metadata` side-channel emits one `FetchMetadata` per account (successful accounts have `fetch_error=None`, failed accounts have `fetch_error` populated and `partial_data=true`).
   - **Cache cursor semantics** (Codex R7#5): `last_sync_by_account` must only be advanced for fully successful account fetches. When a per-account error occurs, that account's cursor stays at its prior value so the missed window is re-fetched on the next run. This prevents permanently skipping missed windows after partial failures. Specifically: move the `last_sync_by_account[account_hash] = end_date.isoformat()` inside the success path, not after the account loop.
   - Slices backed by a failed account automatically become non-authoritative (fetch error present -> coverage check fails -> inference fallback).
4. Both entrypoints return `FetchResult`:

```python
@dataclass
class FetchResult:
    payload: Dict[str, List[Dict[str, Any]]]
    fetch_metadata: List[FetchMetadata]  # empty when metadata unavailable
```

Update both entrypoints consistently:
- `fetch_all_transactions()` -> returns `FetchResult`
- `fetch_transactions_for_source()` -> returns `FetchResult` (for `source="all"` delegates to `fetch_all_transactions()`; for single-source wraps single provider result with its metadata)

**Caller migration checklist** (Codex R4#3 -- exhaustive from `rg`):

| Caller | File | Change |
|--------|------|--------|
| `analyze_realized_performance()` | `core/realized_performance_analysis.py:1770` | Use `result.payload` + `result.fetch_metadata` |
| `get_trading_analysis()` | `mcp_tools/trading_analysis.py:24` | Use `result.payload` |
| `suggest_tax_loss_harvest()` | `mcp_tools/tax_harvest.py:108` | Use `result.payload` |
| `main()` | `run_trading_analysis.py:121` | Use `result.payload` |
| `diagnose_realized` | `tests/diagnostics/diagnose_realized.py:60` | Use `result.payload` |
| Provider routing tests | `tests/trading_analysis/test_provider_routing.py:157,175,204,220` | Use `result.payload` |
| Transaction provider tests | `tests/providers/test_transaction_providers.py:88,113` | Use `result.payload` |

Add contract tests:
- `source="all"` returns `FetchResult` with metadata from all providers
- Single-source returns `FetchResult` with provider-specific metadata
- Missing metadata (provider doesn't support it) returns empty list

For Phase 1, Schwab is the primary provider. Schwab fetch metadata comes from `providers/schwab_transactions.py` via `_last_fetch_metadata` side-channel. For providers without flow extraction (IBKR Flex), metadata is absent and slices remain non-authoritative by default.

### Income Account Identity (Codex R1#2, R2#1)

Slice authority is account-level, but `NormalizedIncome` currently has no `account_id` or `provider_account_ref` -- only `symbol`, `date`, `amount`, `source`, `institution`. This means income events cannot be reliably assigned to authoritative vs non-authoritative slices.

Codex R2#1 correctly noted that `_income_with_currency()` feeds into `derive_cash_and_external_flows()` for cash replay, so income events DO participate in cash/NAV construction -- and without account identity, mixed authoritative/non-authoritative slices can be mis-composed.

Resolution: Add optional `account_id`, `account_name`, and `currency` fields to `NormalizedIncome`:
```python
@dataclass
class NormalizedIncome:
    symbol: str
    income_type: str
    date: datetime
    amount: float
    source: str = "unknown"
    institution: Optional[str] = None
    account_id: Optional[str] = None      # NEW
    account_name: Optional[str] = None     # NEW
    currency: Optional[str] = None         # NEW (Codex R6#3)
```
- These are optional with `None` default -- no rippling changes to existing normalizers that don't populate them.
- Schwab normalizer populates from `txn.get("_account_hash")` and `txn.get("_account_number")` (same fields used in fifo_transactions).
- Other normalizers can populate when available (SnapTrade has `account_id`, Plaid has `account_id`), or leave as `None`.
- `_income_with_currency()` propagates **both** `account_id` and `account_name` into the enriched income dict (Codex R3#4). Both are needed because fallback slice keying uses `account_name` when `account_id` is missing (see partition rule in File-by-File Changes).
- **Blank identifier normalization** (Codex R4#4): Before slice key construction, normalize `account_id` and `account_name`: treat `None`, empty string `""`, and whitespace-only as missing (canonicalize to `None`). This prevents empty strings from being treated as real identifiers, which would collapse unrelated income rows into the same fallback slice key. Apply the same normalization to `fifo_transactions` account fields and provider flow events for consistency.
- **Income currency** (Codex R6#3): Add optional `currency: Optional[str] = None` to `NormalizedIncome`. When populated by the normalizer (Schwab can infer from account currency or transaction `netAmount` currency), `_income_with_currency()` prefers this direct field over symbol-based inference. This prevents mis-pricing in multi-account mixed-currency portfolios where the same ticker trades in different currencies across accounts. When `None`, falls back to current symbol-based inference (backward compatible). Schwab normalizer populates from `transferItems[0].currency` or account-level currency when available.
- Provider-first cash replay uses `account_id` on income events for slice partitioning. When `account_id` is `None` (after normalization), falls back to `account_name` for provisional keying. Income events with both `None` fall through to inference path (fail-open).
- Add tests for: missing-ID fallback partitioning of income events, empty-string identifier normalization, whitespace-only identifier normalization.
- This is a minimal, backward-compatible change -- existing callers that don't use the new fields are unaffected.

### Analysis Period Start (Codex #7)

Current analysis period inception is trade-driven. If provider flows predate the first trade (e.g., a deposit before any buys), the first-month return math is biased because those flows are excluded from period construction.

Resolution: When provider-first mode is enabled, compute analysis start from `min(first_trade_date, first_income_date, first_authoritative_provider_flow_date)`. Pre-trade provider flows become opening contributions in the first period. This ensures deposits that precede trades are captured in the NAV baseline rather than silently omitted.

**Time-bounded authority** (Codex R5#2, R7#4): Authoritative scope for a slice is the intersection of the analysis period and the confirmed authority window. The authority window must reflect **payload coverage** (the range of data actually available), not just the this-run API request window. For Schwab, which merges cached + incremental fetches (`providers/schwab_transactions.py:145-183`), authority window = `(min event date in returned payload for that account, max event date)` when completeness flags are met. `FetchMetadata` should carry both `fetch_window_start/end` (API request range) and `payload_coverage_start/end` (actual data range). Authority uses `payload_coverage_*` when available, falling back to `fetch_window_*`. This prevents cached historical rows from becoming wrongly non-authoritative when metadata reflects only the incremental window. When both are `None`, the slice cannot prove coverage and falls through to the coverage check rules below.

Coverage checks (initial):
1. Slice has at least one eligible provider flow event **or** deterministic "no-flow" confirmation.
2. No known truncation signals from provider pagination/limits in that slice (requires `FetchMetadata`).
3. Institution/source filtering did not drop all provider flow rows while transactions remain present in that slice.
4. Authority applies only within the confirmed fetch window (see time-bounded authority above).

Deterministic "no-flow" confirmation requires all:
1. Provider request completed successfully (no API error/timeout for that slice) -- verified via `FetchMetadata`.
2. Query completeness confirmed:
   - paginated providers: pagination fully exhausted for queried window/accounts
   - non-paginated providers: provider returned full window response for requested query parameters
3. Zero eligible provider flow events after normalization.
4. No truncation flags or partial-data warnings emitted for that slice.
5. **Unmapped row guard** (Codex R8#2): Zero unmapped provider rows in that slice. Extractors must emit per-slice `unmapped_row_count` diagnostics (rows that passed status/family filtering but didn't match any mapping rule). If `unmapped_row_count > 0`, no-flow confirmation fails and the slice remains non-authoritative (inference fallback). This prevents undercounting when new/unknown transaction types appear.

Fee-only window rule:
- A slice with provider-reported fee events but zero external-flow events is considered coverage-confirmed only when truncation/partial-data indicators are absent for that slice.
- In that case:
  - cash replay uses provider fee events
  - external-flow set is provider-authoritative empty
  - inference must **not** inject external flows for that slice
- If truncation/partial-data indicators are present, fee-only slices remain non-authoritative and inference-driven per fallback policy.

Fallback policy:
- `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true`:
  - if coverage check fails for a slice, use inference for that slice and emit warning
  - if coverage check passes, use provider flows for that slice
- `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false`:
  - slices with truncation/partial-data indicators remain non-authoritative and use inference for that slice (provider rows remain diagnostics-only for cash replay and external-flow composition in that slice)
  - slices without truncation/partial-data indicators may use provider flows as authoritative when provider flow events are present, even if deterministic completeness is not proven
  - if a slice has zero eligible provider flow events and lacks deterministic "no-flow" confirmation, keep inference enabled for that slice (fail-open against undercount)
  - if deterministic "no-flow" confirmation is present, treat the slice as authoritative empty for external-flow composition and do not inject inferred external flows
- Inference must run only on non-authoritative slices (source/window/account partitions not covered by provider-authoritative flows) for both cash replay and external-flow composition.
- Never run inference on transactions from provider-authoritative slices (prevents double-counting).

## Feature Flags / Runtime Controls

Add settings (env-backed):

- `REALIZED_USE_PROVIDER_FLOWS` (default `false` initially)
- `REALIZED_PROVIDER_FLOW_SOURCES` (CSV, default `schwab`)
- `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE` (default `true`)

Behavior:
- If provider-first disabled: existing inference-only path.
- If enabled: within enabled sources, provider/inference composition follows the per-slice authority rules above; disabled sources remain inference-only.
- If `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true`: provider flows are used only when coverage checks pass.
- If `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false`:
  - slices with truncation/partial-data indicators remain inference-driven (provider rows retained for diagnostics)
  - for slices without truncation/partial-data indicators, provider flow events may be used as authoritative even when deterministic completeness is not proven
  - if a slice has zero eligible provider flow events and lacks deterministic "no-flow" confirmation, keep inference enabled for that slice (fail-open against undercount)
  - if deterministic "no-flow" confirmation is present, treat the slice as authoritative empty for external-flow composition and do not inject inferred external flows

## Rollback Plan (Codex #13)

Rollback is controlled by a single master toggle. The other flags are subordinate:

1. Set `REALIZED_USE_PROVIDER_FLOWS=false`.
2. When this flag is `false`, `REALIZED_PROVIDER_FLOW_SOURCES` and `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE` are ignored -- they have no effect.
3. System returns to inference-only without schema rollback.

Document in settings.py that `REALIZED_USE_PROVIDER_FLOWS=false` is the sole rollback action; the other flags are operational controls that only matter when the master toggle is on.

---

## File-by-File Changes

### New Files

1. `providers/flows/common.py`
- Shared helpers for date/amount/currency parsing and sign normalization.
- Flow dataclass/TypedDict definition.
- `FetchMetadata` TypedDict definition.
- `build_slice_key()` — canonical slice-key builder used everywhere (Codex R6#4).
- **Timestamp normalization** (Codex R6#5): All provider event timestamps must be normalized to naive UTC before storage. Define `normalize_event_time(raw_datetime) -> datetime` that converts aware datetimes to UTC then strips tzinfo, and leaves naive datetimes as-is (assumed UTC). Store both `timestamp` (full precision, naive UTC) and `event_day_utc` (date only) on each flow event. Dedup sorting and transfer day-matching must use only these normalized fields. This prevents mixed naive/aware comparison errors and ensures consistent day-bucketing across providers.

2. `providers/flows/schwab.py`
- `extract_schwab_flow_events(raw_rows) -> list[dict]`
- Status gating: skip non-VALID rows.
- Margin interest fee extraction from `DIVIDEND_OR_INTEREST`.
- Uses shared `SCHWAB_TRADE_ACTIONS` enum from normalizer to exclude trade rows.

3. `providers/flows/plaid.py`
- `extract_plaid_flow_events(raw_rows) -> list[dict]`

4. `providers/flows/snaptrade.py`
- `extract_snaptrade_flow_events(raw_rows) -> list[dict]`

5. `providers/flows/ibkr_flex.py`
- `extract_ibkr_flex_flow_events(raw_rows) -> list[dict]` (phase-1 no-op, returns `[]`, explicit reason in comments)

6. `providers/flows/extractor.py`
- Orchestrator to extract normalized flow events from fetched provider payload.
- Receives `FetchResult` (payload + metadata from fetcher layer).
- Returns `(events, fetch_metadata)` -- events from extractors, metadata passthrough from `FetchResult`.

7. `providers/flows/__init__.py`
- Re-export extraction entry points.

8. `tests/providers/flows/test_schwab_flows.py`
9. `tests/providers/flows/test_plaid_flows.py`
10. `tests/providers/flows/test_snaptrade_flows.py`
11. `tests/providers/flows/test_extractor.py`

### Existing Files

1. `settings.py`
- Add provider-flow feature flags.

2. `core/realized_performance_analysis.py`
- After `fetch_transactions_for_source(...)`, extract provider flow events from payload.
- Add institution filtering for provider flow events (same filter semantics as transactions).
- **Filter FetchMetadata by institution** (Codex R8#1): Apply the same institution routing filter to `FetchMetadata` entries before coverage gating. Metadata from accounts/institutions that are filtered out by routing must not influence authority decisions for remaining slices.
- Include provider flow currencies/dates in FX range construction.
- Extend analysis period start to include authoritative provider flow dates (Codex #7).
- Add provider-first flow path:
  - provider flow events are authoritative only for slices that satisfy authority rules:
    - coverage-confirmed slices when `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true`
    - non-truncated/non-partial slices with provider-flow eligibility when `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false`
  - inference runs on uncovered/non-authoritative slices (including slices within enabled sources)
- Apply provider-first composition to both NAV branches currently used by realized analysis:
  - synthetic-enhanced flow path
  - observed-only flow path
- Prefer a shared helper to avoid branch drift (same flow composition rules in both branches).
- Apply provider-flow dedup before coverage checks and flow composition.
- Partition rule (mandatory):
  - **Canonical slice-key builder** (Codex R6#4): A single `build_slice_key()` function in `providers/flows/common.py` used by all partitioning, coverage gating, and FetchMetadata matching. Resolves `account_id`, `provider_account_ref`, and `account_name` with consistent precedence.
  - build authoritative slice keys using `(source, account_id_or_provider_account_ref, date_window)`
  - if both `account_id` and `provider_account_ref` are missing, use provisional fallback key `(source, institution, account_name_or_unknown, date_window)`
  - fail-closed on fallback-key collisions: if provisional key maps to multiple raw accounts in-window, mark slice non-authoritative and keep inference enabled for that slice
  - exclude authoritative-slice transactions from inference input
  - run inference only on residual slices
- **Synthetic cash event handling** (Codex R5#3): Synthetic cash events (`source="synthetic_cash_event"` in `realized_performance_analysis.py:1088`) currently lack account identity. In mixed authoritative/non-authoritative runs, these cannot be reliably attributed to a specific account slice. For Phase 1: exclude synthetic cash events from provider-first slice partitioning entirely -- they participate only in the inference/legacy path. Synthetic events are already inference-derived (position gap fills), so they belong to the inference domain. If a slice is provider-authoritative, synthetic events for that slice's positions are suppressed (provider flows replace them). If non-authoritative, synthetic events are included as before. Future enhancement: add account attribution to synthetic events when position-to-account mapping is available.
- Split cash replay and external-flow derivation:
  - cash replay consumes trade/income + provider cash-impact events (including fees) only for authoritative slices; non-authoritative slices remain inference-driven
  - `external_flows` consume only normalized provider events with `is_external_flow=true` from authoritative slices, plus inferred fallback slices
  - provider-flow rows from non-authoritative slices remain diagnostics-only for cash replay and external-flow composition (prevents double-counting in mixed fallback slices)
- Keep existing `derive_cash_and_external_flows(...)` behavior as compatibility fallback only when provider-first mode is disabled (`REALIZED_USE_PROVIDER_FLOWS=false`) or when provider-flow extraction is globally unavailable before slice partitioning.
- "Globally unavailable" means extractor infrastructure is not initialized/usable for the run before any source-slice evaluation (startup-level failure). It does **not** include per-source/per-slice extraction errors.
- Per-source/per-slice extraction errors must stay in provider-first mode and be handled as non-authoritative slices with inference fallback plus diagnostics.
- Do not mix this compatibility fallback with provider-first slice composition in the same run.
- Add warnings describing flow source mix (provider vs inferred).
- Add realized-output diagnostics:
  - `flow_source_breakdown` (counts by source with explicit buckets: `provider_authoritative_applied`, `provider_diagnostics_only`, `inferred`)
  - `provider_flow_coverage` summary per slice (source/window/account key) with optional source rollup
  - `flow_fallback_reasons` when inference is used
  - `dedup_diagnostics` (duplicate-drop counts by source/provider and slice key)
- Preserve existing `net_contributions` field as legacy trade-derived metric and document it explicitly.
- Add additive metric(s) for provider-flow semantics:
  - `external_net_flows_usd` (sum of normalized external flows in analysis window)
  - `net_contributions_definition` (e.g., `trade_cash_legs_legacy` vs `provider_external_flows`)

3. `tests/core/test_realized_performance_analysis.py`
- Add tests for provider-first behavior and fallback logic.
- Ensure existing inference tests remain valid under disabled flag.

4. `tests/providers/test_interfaces.py`
- No protocol changes expected; add coverage to ensure no interface regressions.

5. `tests/providers/test_transaction_providers.py`
- Keep existing behavior; add optional assertions that raw payload still passes through unchanged for flow extraction.

6. `core/result_objects.py`
- Extend `RealizedMetadata` to include new flow diagnostics fields:
  - `flow_source_breakdown`
  - `provider_flow_coverage`
  - `flow_fallback_reasons`
  - `dedup_diagnostics`
- Add additive flow/definition fields:
  - `external_net_flows_usd`
  - `net_contributions_definition`
- Ensure `from_dict()` defaults preserve backward compatibility for old payloads.
- Ensure `to_dict()` emits new fields consistently.

---

## Detailed Implementation Phases

## Phase 0: Preconditions

1. Land Schwab normalizer gating fix (non-trade rows not converted to trades).
2. Confirm no pending breakage in realized performance baseline tests.
3. Confirm Schwab trade-family mapping supports both observed forms:
   - action-style rows (`BUY`, `SELL`, `SHORT`, `COVER`)
   - family-style rows (`TRADE` + subtype/activity fields)

Exit criteria:
- `tests/providers/test_schwab_normalizer.py` passes with gating behavior.
- `tests/core/test_realized_performance_analysis.py` baseline pass before flow integration starts.

## Phase 1: Flow Extraction Infrastructure

1. Implement `providers/flows/*` modules and extractor orchestrator.
2. Add deterministic unit tests for each provider mapper.
3. Include `FetchMetadata` propagation from provider fetch to extractor return.

Exit criteria:
- Flow extractor tests pass.
- Extracted events have canonical sign and schema.
- `FetchMetadata` populated for Schwab; absent/empty for IBKR Flex.

## Phase 2: Core Integration (Flag Off by Default)

1. Wire extraction into `analyze_realized_performance`.
2. Add slice-aware provider-first + inference-fallback flow composition.
3. Extend analysis period start to include provider flow dates.
4. Keep output contract backward compatible; allow additive realized metadata fields for diagnostics.

Exit criteria:
- Existing realized performance tests pass unchanged.
- New provider-first tests pass with feature flag on.

## Phase 3: Rollout

1. Enable for `schwab` only.
2. Run shadow comparisons:
   - inference-only vs provider-first
   - monthly NAV and monthly returns deltas
3. **Prerequisite for Plaid/SnapTrade expansion** (Codex R7#6): Before enabling provider flows for Plaid/SnapTrade, implement minimal `FetchMetadata` for those providers (at least `pagination_exhausted`, `fetch_error`, and `payload_coverage_start/end`). Without metadata, coverage gating cannot function (`REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true` will always fail). Alternatively, expansion can proceed with `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false` and documented risk that provider flows may be incomplete.
4. Expand to `snaptrade` and `plaid` after metadata implementation + review.

Exit criteria:
- No material unexplained regressions in shadow runs.
- Data quality warnings are within expected range.

## Phase 4: IBKR Enhancement (Separate Follow-Up)

1. Extend IBKR ingestion beyond `Trade` rows (cash sections in Flex).
2. Add IBKR flow extractor implementation and tests.

Exit criteria:
- IBKR included in provider-first flow path.

---

## Test Plan

### Unit Tests (Provider Flow Mappers)

1. Schwab inflow/outflow mapping by `type`.
2. Schwab `JOURNAL`/`ELECTRONIC_FUND` conservative default-to-transfer behavior (Codex #9).
3. Schwab margin interest fee extraction from `DIVIDEND_OR_INTEREST` (Codex #4).
4. Schwab status gating: `PENDING`/`CANCELED`/`INVALID` rows excluded (Codex #5).
5. Plaid subtype mapping (`contribution`, `withdrawal`) and sign normalization.
6. SnapTrade `CONTRIBUTION/WITHDRAWAL/FEE/TRANSFER` mapping.
7. Transfer netting helper behavior.
8. Fee classification is non-external across providers.
9. Exhaustive Schwab type coverage test to ensure no silent default path.
10. Dedup behavior:
   - transaction-id key dedup
   - fallback fingerprint dedup when `transaction_id` missing
   - false-positive guard: two legitimate same-day same-amount events with distinct raw identity are both preserved
   - fail-open guard: rows with insufficient fallback identity are not deduplicated
   - deterministic winner selection (sorted key, not ingestion order) (Codex #12)
11. Transfer netting one-to-one behavior:
   - unique pair nets
   - many-to-many bucket remains unmatched with warning
   - linkage-field tie-breaking (Codex #11)
12. `FetchMetadata` populated correctly by Schwab fetcher layer (via `_last_fetch_metadata` side-channel).

### Core Logic Tests

1. Provider-authoritative slice present -> no inferred injection for that slice; inference remains allowed on residual non-authoritative slices.
2. Mixed sources:
   - covered provider-authoritative slices use provider events
   - non-provider source still uses inference
3. Institution filter applies consistently to provider flows and transactions.
4. Provider-flow currency is included in FX cache requirements.
5. Disabled flag preserves exact legacy behavior.
6. With `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=true`, coverage failure for provider slice triggers inference fallback for that slice.
7. `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false` with partial/truncated slice keeps that slice non-authoritative: inference remains enabled and provider rows are diagnostics-only for cash replay and external-flow composition.
8. `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false` on non-truncated slice with provider events allows provider-authoritative flow composition even when deterministic completeness is not proven.
9. `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false` with zero eligible provider-flow rows and no deterministic no-flow confirmation keeps inference enabled for that slice.
10. `REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE=false` with deterministic no-flow confirmation treats the slice as authoritative empty and does not inject inferred external flows.
11. Extractor globally unavailable at startup triggers compatibility fallback path, and provider-first slice composition is not mixed into that run.
12. Deterministic no-flow slice (complete query + zero eligible flow events) is coverage-confirmed and does not trigger inferred external flows.
13. Ambiguous transfer events do not net silently.
14. Provider fee event decreases cash/NAV but does not appear in `external_flows`.
15. Realized output diagnostics include `flow_source_breakdown` bucketed as (`provider_authoritative_applied`, `provider_diagnostics_only`, `inferred`) plus slice-level coverage/fallback fields.
16. Authoritative provider slices are excluded from inference input (no duplicate flow counting).
17. Fee-only provider slice is coverage-confirmed and does not trigger inferred external flows.
18. Fee-only slice with truncation/partial-data indicators remains non-authoritative and inference-driven.
19. Synthetic-enhanced and observed-only NAV branches both use the same provider-first flow composition rules.
20. `net_contributions` remains legacy trade-derived, and `external_net_flows_usd` matches external-flow totals.
21. Non-cash transfer events do not enter `external_flows`.
22. Deduplicated provider flow rows do not double-count cash replay or `external_flows`; `dedup_diagnostics` is present in realized metadata with source/provider and slice-key counts.
23. Missing-identifier fallback-key collision fails closed: slice remains non-authoritative and inference remains enabled for that slice.
24. Many-to-many transfer candidates remain unmatched and produce ambiguity warnings.
25. Analysis period start includes pre-trade provider flows as opening contributions (Codex #7).
26. Coverage gating uses `FetchMetadata` for truncation/completeness decisions (Codex #1).
27. Provider fetch error does not abort other providers; failed provider's slices become non-authoritative (Codex R5#1).
28. Authority bounded to confirmed fetch window; out-of-window transactions use inference (Codex R5#2).
29. Synthetic cash events excluded from provider-first slice partitioning; suppressed in authoritative slices (Codex R5#3).
30. Per-account Schwab fetch error: failed account emits error metadata, other accounts remain usable (Codex R6#2).
31. Income currency prefers direct `NormalizedIncome.currency` over symbol-based inference when populated (Codex R6#3).
32. Timestamp normalization: mixed naive/aware datetimes produce consistent naive-UTC dedup keys (Codex R6#5).
33. Canonical `build_slice_key()` produces consistent keys from flow events, FetchMetadata, and income events (Codex R6#4).

### Integration Tests (Codex #14)

1. Routed payloads + institution filter parity across transactions and provider flows under `source=all`.
2. Single-source fetch path (`source="schwab"`) produces correct authoritative/non-authoritative slices.
3. Mixed authoritative/non-authoritative slices in same run with provider-routing active.
4. Provider-routing partition does not drop flow events that should remain (empty institution preserved).

### Regression Tests

1. Full run of `tests/core/test_realized_performance_analysis.py`
2. Existing provider normalizer suites:
   - `tests/providers/test_schwab_normalizer.py`
   - `tests/providers/normalizers/test_plaid.py`
   - `tests/providers/normalizers/test_snaptrade.py`
   - `tests/providers/normalizers/test_ibkr_flex.py`
3. Result-object compatibility tests:
   - `tests/mcp_tools/test_performance.py`
   - `tests/services/test_portfolio_service.py`

---

## Risks and Mitigations

1. Sign normalization errors across providers
- Mitigation: provider-specific fixture tests and explicit comments with source conventions.

2. Double-counting external flows and trade cash legs
- Mitigation: strict event taxonomy and transfer netting; keep trades out of external-flow list.

3. Partial provider payload coverage
- Mitigation: per-slice fallback to inference plus explicit warnings; `FetchMetadata` for coverage gating.

4. Mixed-provider portfolios with uneven flow support
- Mitigation: slice-aware hybrid logic (provider-first where available, inference elsewhere).

5. Internal sweeps/transfers misclassified as external flows (Codex #9)
- Mitigation: `JOURNAL`/`ELECTRONIC_FUND` default to transfer/non-external; require explicit evidence for external-flow promotion.

---

## Deliverables

1. New provider flow extraction modules with tests.
2. Provider-first flow composition in realized performance engine (flagged rollout).
3. Updated planning docs and rollout checklist.

---

## Codex Review

### Round 1 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Coverage gating requires truncation/completeness signals but fetch path has no metadata | Added `FetchMetadata` structure; R2: specified fetch-layer contract change -- `fetch_all_transactions()` returns `(payload, fetch_metadata_list)` tuple |
| 2 | HIGH | Income events lack account identity -- can't do account-level slice authority | R2: Add optional `account_id`/`account_name` to `NormalizedIncome`; Schwab populates from `_account_hash`/`_account_number`; income with `None` falls through to inference |
| 4 | HIGH | Margin interest/fee debits under DIVIDEND_OR_INTEREST excluded -- overstates performance | Parse negative interest from DIVIDEND_OR_INTEREST as `flow_type=fee`, `is_external_flow=false` for cash replay drag |
| 5 | HIGH | No status gating (VALID vs PENDING/CANCELED) | Added status filter requirement to Schwab flow extractor (same as normalizer fix plan) |
| 7 | HIGH | Provider flows predating first trade excluded from period construction | Analysis start extended to min(trades, income, authoritative provider flows) |
| 9 | MED | JOURNAL/ELECTRONIC_FUND sign-based mapping risks misclassifying sweeps | Changed to conservative default-to-transfer with explicit evidence required for external-flow promotion |
| 11 | MED | Transfer netting false-nets unrelated same-amount flows | Strengthened pairing with linkage fields and conservative no-net fallback |
| 12 | MED | Dedup "keep first by ingestion order" non-deterministic | Changed to deterministic sort key before dedup |
| 13 | LOW | Rollback isn't truly "one flag" | Documented REALIZED_USE_PROVIDER_FLOWS as sole rollback toggle; subordinate flags ignored when off |
| 14 | LOW | Missing integration tests for routing + institution filtering | Added Integration Tests section with 4 routing-aware test scenarios |

### Round 2 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | R1#2 not adequately resolved: income events in `_income_with_currency()` feed cash replay without account identity, mis-composing mixed slices | Added optional `account_id`/`account_name` to `NormalizedIncome` (backward-compatible None defaults); Schwab populates from `_account_hash`/`_account_number`; income with `None` falls through to inference |
| 2 | HIGH | R1#6 not adequately resolved: security_lookup wired from Plaid (keyed by security_id), not useful for Schwab dividend resolution | Moved to Schwab normalizer plan: dedicated `schwab_security_lookup` input built from Schwab positions, separate from Plaid security_lookup |
| 3 | HIGH | R1#1 partially resolved: FetchMetadata requires fetch-layer payload contract changes but `_merge_payloads()` drops unknown keys | Specified approach: `fetch_all_transactions()` returns `(payload, fetch_metadata_list)` tuple; metadata separate from payload merge path |
| 4 | MED | Subtype logic uses only `transactionSubType` but Schwab also has `activityType`; misses REINVEST/INTEREST classification | Added shared resolved subtype pattern in Schwab normalizer plan Bug 3; flow extractor uses same pattern for interest fee classification |
| 5 | MED | REINVEST buy-leg extraction under-specified for multi-leg transferItems | Moved to Schwab normalizer plan Bug 5: explicit non-currency leg selection with ambiguity fallback |

### Round 3 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Subtype classification order: REINVEST_DIVIDEND contains "DIVIDEND" | Moved to Schwab plan Bug 3: priority order explicit (REINVEST first), prefer exact enum matching |
| 2 | HIGH | fetch_transactions_for_source() not updated for metadata; source=all callers expecting dict break | Replaced tuple approach with `FetchResult` dataclass used by BOTH fetch entrypoints; all callers updated |
| 3 | MED | schwab_security_lookup as normalize() kwarg changes Protocol | Moved to Schwab plan Bug 4: constructor injection, Protocol unchanged |
| 4 | MED | _income_with_currency() propagates only account_id, not account_name needed for fallback keying | Updated to propagate both; added tests for missing-ID fallback partitioning |

### Round 4 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | FetchMetadata transport hand-wavy -- how does metadata get from provider to fetcher when `_merge_payloads()` drops unknown keys? | Specified concrete transport: `_last_fetch_metadata` side-channel on providers; metadata collected in fetcher loop BEFORE `_merge_payloads()` call; accumulated in separate `fetch_metadata_list` |
| 2 | HIGH | schwab_security_lookup wiring ambiguous -- which callers build/pass it? | Addressed in Schwab plan Bug 4: canonical wiring path with shared builder, single injection point (`TradingAnalyzer.__init__`), exhaustive 4-caller table |
| 3 | MED | `FetchResult` callers not exhaustively listed -- breaking change risk | Added caller migration checklist table with all 7 callsites from `rg` (4 production + 3 test files) |
| 4 | MED | Blank `account_id`/`account_name` (empty string, whitespace) treated as real identifiers -- collapses unrelated rows | Added blank identifier normalization: canonicalize None/empty/whitespace to None before slice key construction; apply to fifo_transactions and provider flow events too |

### Round 5 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Fetch error fallback not implementable -- current fetch path hard-fails on provider exceptions, aborting before slice fallback can happen | Added fetch error resilience: `fetch_all_transactions()` catches per-provider exceptions, emits `FetchMetadata` with `fetch_error`, continues to next provider; hard-fail only when no usable data remains |
| 2 | HIGH | Authoritative coverage not bounded to fetched time windows -- slices incorrectly authoritative for out-of-window periods | Added time-bounded authority: scope = intersection of analysis period and confirmed `fetch_window_start/end`; outside that range, force non-authoritative/inference |
| 3 | HIGH | Synthetic cash events lack account identity -- misattribution in mixed authoritative/non-authoritative runs | Synthetic events excluded from provider-first partitioning (Phase 1); suppressed in authoritative slices, included in inference slices; future enhancement to add account attribution |
| 4 | MED | FetchMetadata ownership split between fetcher and extractor causes implementation drift | Clarified: fetcher layer is sole owner of FetchMetadata; extractors return events only (`list[dict]`); orchestrator receives both and passes through |
| 5 | MED | Schwab trade-action allowlist incomplete -- missing option open/close variants | Addressed in Schwab plan Bug 1: shared `SCHWAB_TRADE_ACTIONS` enum includes `BUY_TO_OPEN`, `SELL_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_CLOSE`, `EXCHANGE` |
| 6 | MED | schwab_security_lookup prefetch over-eager -- fails unrelated non-Schwab runs | Addressed in Schwab plan Bug 4: lazy guard -- only fetch when Schwab transactions present in payload or source includes Schwab |

### Round 6 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Missing action-to-TradeType mapping for newly allowed Schwab trade actions -- sign-based fallback misclassifies options | Addressed in Schwab plan Bug 1: shared `SCHWAB_ACTION_TO_TRADE_TYPE` dict with explicit mapping for all 11 actions |
| 2 | HIGH | Fetch-error resilience only provider-level; one Schwab account failure drops all Schwab data | Added per-account error isolation in `SchwabTransactionProvider`: continue other accounts, return partial payload, emit per-account `FetchMetadata` entries |
| 3 | HIGH | Income currency inferred by symbol only -- wrong in multi-account mixed-currency portfolios | Added optional `currency` field to `NormalizedIncome`; `_income_with_currency()` prefers direct field over symbol-based inference |
| 4 | MED | Flow schema missing `account_name`; FetchMetadata overloads `account_id` with `provider_account_ref` | Added `account_name` and `provider_account_ref` as separate fields to both schemas; canonical `build_slice_key()` builder in `common.py` |
| 5 | MED | Timestamp normalization unspecified -- mixed naive/aware datetimes break dedup/netting | Added `normalize_event_time()` in `common.py`: all events to naive UTC; `event_day_utc` field for day-bucketing |

### Round 7 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Description map built only from `type=TRADE` rows, misses action-style trade rows | Addressed in Schwab plan Bug 2: map built using same trade predicate as normalization (status + family/action + non-currency guard) |
| 2 | MED | `get_schwab_security_lookup()` failure behavior unspecified -- can abort analysis | Addressed in Schwab plan Bug 4: fail-open -- catch/log errors, return `None` |
| 3 | MED | Dedup identity doesn't use canonical account resolver -- false dedup across accounts | Dedup key now uses `canonical_account_identity` from `build_slice_key()` account resolver |
| 4 | HIGH | Authority window from API request range only -- cached rows wrongly non-authoritative | Added `payload_coverage_start/end` to `FetchMetadata`; authority uses payload coverage (actual data range), not just request window |
| 5 | HIGH | Per-account error: cache cursor advanced after failure permanently skips windows | Added strict cursor semantics: only advance `last_sync_by_account` for fully successful accounts |
| 6 | MED | Plaid/SnapTrade rollout impossible with `REQUIRE_COVERAGE=true` when metadata is empty | Added prerequisite: implement minimal FetchMetadata before enabling, or use `REQUIRE_COVERAGE=false` with documented risk |

### Round 8 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | FetchMetadata has no `institution` field -- authority decisions use metadata from filtered-out accounts | Added `institution` to `FetchMetadata`; institution routing filter applied to metadata before coverage gating |
| 2 | HIGH | Deterministic no-flow grants authority even when unmapped rows exist | Added unmapped row guard: extractors emit `unmapped_row_count`; if >0, no-flow confirmation fails |
| 3 | MED | REINVEST income amount source unspecified when netAmount is zero | Addressed in Schwab plan Bug 5: extraction order (cash-leg -> price*qty -> abs(netAmount)); zero = skip both legs |
| 4 | HIGH | Negative DIVIDEND_OR_INTEREST subtypes (TAX_WITHHOLDING etc.) converted to positive income via abs() | Added shared debit-subtype policy in Schwab plan Bug 3: preserve sign, gate abs() on resolved subtype |
| 5 | MED | `_last_fetch_metadata` stale across reused provider instances | Added reset semantics: clear to None at fetch start; fetcher treats None as unavailable |
