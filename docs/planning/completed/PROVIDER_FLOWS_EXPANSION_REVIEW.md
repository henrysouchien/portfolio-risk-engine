# Provider Flows Expansion Review

Date: 2026-02-17
Reviewed docs:
- `docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md`
- `docs/planning/PROVIDER_API_RESEARCH.md`

## Findings

### 1) Plan ↔ Research Consistency

- **[HIGH] Plaid metadata granularity is inconsistent between research and authority requirements.**
  Research says metadata should be emitted at the per-token level (`docs/planning/PROVIDER_API_RESEARCH.md:49`), but authority keying is account-scoped (`core/realized_performance_analysis.py:1639`, `core/realized_performance_analysis.py:1642`, `core/realized_performance_analysis.py:1698`) and Plaid events carry account identity (`providers/flows/plaid.py:40`). If implemented as token-level rows (no account key), slices will fall back as `missing_fetch_metadata`.

- **[MED] IBKR section scope is not fully resolved between plan and research.**
  Research recommends CashTransactions as primary and ignoring Transfers initially (`docs/planning/PROVIDER_API_RESEARCH.md:249`), but the plan says “non-Trade sections” without explicit precedence/dedup policy (`docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md:162`).

### 2) Existing Code Alignment

- **[HIGH] Research overstates reliance on `ibflex`; current runtime behavior is `ib_async` tag-based extraction.**
  Code uses `ib_async.FlexReport` directly (`ibkr/flex.py:13`, `ibkr/flex.py:377`). Installed `FlexReport.extract()` iterates exact XML tags (`/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/ib_async/flexreport.py:59`, `/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/ib_async/flexreport.py:67`). Also, repo dependency lists `ib_async` but not `ibflex` (`requirements.txt:45`).

- **[MED] Research does not capture IBKR fail-open behavior that affects metadata semantics.**
  `fetch_ibkr_flex_trades()` returns `[]` on missing credentials/download/parse failure (`ibkr/flex.py:361`, `ibkr/flex.py:373`, `ibkr/flex.py:380`), and provider wrapper returns that as normal payload (`providers/ibkr_transactions.py:15`, `providers/ibkr_transactions.py:19`). This is important for Phase 4 `fetch_error`/`partial_data` logic.

### 3) FetchMetadata Mapping Completeness

- **[MED] SnapTrade coverage mapping should mirror extractor date fallback, not only `trade_date`.**
  Research maps coverage from `trade_date` only (`docs/planning/PROVIDER_API_RESEARCH.md:89`), but flow extraction uses `trade_date` OR `settlement_date` OR `date` (`providers/flows/snaptrade.py:26`). Authority checks event date against coverage bounds (`core/realized_performance_analysis.py:1741`).

- **[HIGH] IBKR “pagination_exhausted always true” is incomplete unless success/failure is surfaced separately.**
  Research marks batch reports as always exhausted when successful (`docs/planning/PROVIDER_API_RESEARCH.md:194`), but current fetch API collapses several failure modes into empty payload (`ibkr/flex.py:361`, `ibkr/flex.py:373`, `ibkr/flex.py:380`). Metadata generation needs explicit success/failure signal beyond row count.

- **[MED] Empty-page-before-total edge case needs explicit SnapTrade handling.**
  SnapTrade loop exits on empty page (`trading_analysis/data_fetcher.py:154`) and separately checks `offset >= total` (`trading_analysis/data_fetcher.py:173`). Metadata should only set `pagination_exhausted=True` when exhaustion is proven (similar to plan’s conservative rule, `docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md:112`).

### 4) IBKR CashTransaction Integration Feasibility

- **[MED] Integration is feasible, but extract topic naming must be validated against actual XML tags.**
  `FlexReport.extract(topic)` is tag-name based and case-sensitive (`/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/ib_async/flexreport.py:59`, `/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/ib_async/flexreport.py:67`), which matches research’s naming caution (`docs/planning/PROVIDER_API_RESEARCH.md:218`, `docs/planning/PROVIDER_API_RESEARCH.md:253`).

- **[LOW] `parseNumbers=True` can coerce numeric-looking IDs, affecting transaction-id stability.**
  `extract()` auto-parses attributes to numeric types (`/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/ib_async/flexreport.py:68`). If IDs are used for dedup keys, preserve raw strings or normalize deterministically.

### 5) Dedup / Overlap Risks

- **[MED] CashTransactions vs Transfers overlap is identified but not operationalized in the plan.**
  Research flags overlap (`docs/planning/PROVIDER_API_RESEARCH.md:216`) and recommends source precedence (`docs/planning/PROVIDER_API_RESEARCH.md:249`), but plan does not define dedup precedence at ingestion/mapping time (`docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md:162`, `docs/planning/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md:168`).

- **[MED] Provider-flow dedup may collapse legitimate multi-leg IBKR cash events if `transaction_id` is reused.**
  Dedup prioritizes `(provider, account-identity, transaction_id)` (`core/realized_performance_analysis.py:1576`). If IBKR emits same ID across related but distinct rows, one can be dropped.

### 6) Missing Risks / Gaps

- **[LOW] Plan should explicitly require warning/diagnostics when `CashTransaction` section is absent.**
  Research calls this out (`docs/planning/PROVIDER_API_RESEARCH.md:214`, `docs/planning/PROVIDER_API_RESEARCH.md:251`), but plan phases do not explicitly include runtime warning acceptance criteria.

- **[LOW] Source-specific fetch path lacks provider error-metadata fallback parity with all-provider path.**
  `fetch_all_transactions()` emits provider error metadata on exceptions (`trading_analysis/data_fetcher.py:403`, `trading_analysis/data_fetcher.py:405`), while `fetch_transactions_for_source()` directly calls provider fetch without that fallback (`trading_analysis/data_fetcher.py:442`). This can hide diagnostics during source-scoped testing.

## Overall Assessment

The phase structure is directionally good and mostly aligned with current architecture. The highest-risk items to resolve before implementation are:
1. Lock metadata slice granularity to account-level for Plaid/SnapTrade/IBKR.
2. Add explicit IBKR success/failure signaling so Phase 4 metadata is trustworthy.
3. Define IBKR cash-source precedence/dedup policy (CashTransaction vs Transfer) before mapping implementation.
