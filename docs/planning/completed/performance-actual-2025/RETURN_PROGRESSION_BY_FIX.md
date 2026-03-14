# Realized Performance: Return Progression by Fix Phase

**Root investigation**: `docs/planning/REALIZED_PERF_DATA_QUALITY.md`

## Broker Actuals (Ground Truth)

| Account | Broker Reported Return | Period |
|---------|----------------------|--------|
| IBKR (U2471778) | **-9.35%** | 2025 calendar year |
| IBKR (U2471778) | **+0.29%** | Apr 2025 – Mar 2026 (statement) |
| Schwab 165 | **-8.29%** | 2025 calendar year |
| Schwab 013 | **-14.69%** | 2025 calendar year |
| Schwab 252 | **+10.65%** | 2025 calendar year |
| **Schwab aggregate** | **~+5.6%** | 2025 cal year (NAV-weighted: 252 74%, 165 24%, 013 2%) |
| Merrill Edge (Plaid) | **-12.49%** | 2024-01 to 2025-12 |

Sources: `baseline_extracted_data.json`, broker statements in `performance-actual-2025/`

### Per-Source / Per-Account Accuracy (updated 2026-03-08)

| Account | System (Mar 7) | System (Mar 8) | Broker | Gap (latest) | Notes |
|---------|---------------|---------------|--------|-------------|-------|
| Schwab 165 | -8.32% | -7.35% | -8.29% | **0.94pp** | TWR track accurate. NAV P&L diverges but headline return correct. |
| Schwab 013 | -3.20% | +2.36% | -14.69% | **17.05pp** | Tiny $2K account (2% weight). Cash anchor denominator sensitivity. Low priority. |
| Schwab 252 | +9.55% | +13.13% | +10.65% | **2.48pp** | TWR vs XIRR methodology + FMP vs Schwab pricing ($1,351 / 2.5% NAV diff). Data quality verified clean. |
| Schwab aggregate | +5.09% | +9.70% | ~+5.6% (weighted) | **~4.1pp** | TWR aggregate pulled by 252 gap. |
| IBKR | +2.60% | -0.19% | +0.29% (statement) | **0.48pp** | ✅ Dual cash anchor working. |
| Plaid (Merrill) | — | -11.36% | -12.49% | **1.13pp** | ✅ Stable. |

---

## Total Return Progression

| Source | Baseline (pre-P1) | After #1 P1 | After #2-#5 (P2A+P2B) | After #6 P3 | After #7 P3.1 | After #8 P3.2 | After #9 Schwab A/E/F/G | After #10 Remove Extreme Filter | After #13 Fix J | After #14-16 Flex P2 + fixes | After #17 Synthetic TWR flows | After #18 Price Alignment | Broker Actual |
|--------|-------------------|-------------|------------------------|-------------|---------------|---------------|-------------------------|--------------------------------|-----------------|-------------------------------|-------------------------------|---------------------------|---------------|
| **Combined** | -64.37% | +83.91% | +188.08% | -23.84% | +34.66% | +34.66% | +34.41% | +34.41% | +34.41% | TBD | TBD | **TBD** | -8 to -12% |
| **IBKR Flex** | (in combined) | +126.32% | -68.88% | -100.00% | +10.45% | +10.45% | -71.78% | +15.27% | -11.37% | -32.53% | -24.80% | **-8.04%** | -9.35% |
| **Schwab** | (in combined) | +142.79% | +51.36% | +49.76% | +49.76% | +33.13% | +23.13% | +23.13% | +23.13% | +17.53% | +17.53% | **+17.53%** | -8.29% |
| **Plaid (Merrill)** | (in combined) | +1.32% | -7.96% | -7.96% | -7.96% | -7.96% | -12.93% | -12.93% | -12.93% | +1.21% | +1.21% | **-11.77%** | -12.49% |

Column mapping:
- **Baseline**: Before any fixes. Observed-only track (sensitivity gate fired).
- **After #1 P1** (`efd8f1a6`): UNKNOWN/fx filtering + futures inference gating.
- **After #2-#5** (`eb9fc423` → `1d943108`): P2A synthetic cash exclusion + diagnostic-only gate + source attribution hardening + observed-only branch fix + P2B futures fee-only + income dedup.
- **After #6 P3** (`0e533cb7`): Global inception + futures incomplete trade filter.
- **After #7 P3.1** (`6c2f6e89`): Futures compensating events + incomplete trade synthetics at inception.
- **After #8 P3.2**: Schwab cross-source attribution fix (native-over-aggregator tiebreaker).
- **After #9 Schwab A/E/F/G**: Per-account aggregation, cash-back/timestamp/inception deferral, per-symbol synthetic inception, system transfer BUY + contribution. IBKR regressed to -71.78% (extreme month filter side-effect).
- **After #10 Remove Extreme Filter**: Removed `extreme_month_filter_active` gate that NaN-ified months >300% when synthetic tickers present. Restored IBKR March 2025 +308% to chain-linking.
- **After #13 Fix J** (`3ce88f1c`): Futures daily MTM settlement. IBKR -11.37% (was +15.27%).
- **After #14-16 Flex P2 + fixes** (`f4dac23f`, `fe297eda`, `264c2940`): Flex Phase 2 polling exposed StmtFunds + ghost account bugs. Fixed both, but 19 synthetic positions now create TWR distortion. IBKR -32.53%.

### Key observations (updated 2026-03-03)

- **IBKR** ✅ solved: -8.04% vs -9.35% actual (1.31pp). Price alignment fix (#18) was the final piece — aligned synthetic TWR flow prices with NAV cache prices. Remaining gap explained by period mismatch (system Mar '25–Feb '26 vs broker calendar 2025).
- **Plaid** ✅ solved: -11.77% vs -12.49% actual (0.72pp). Unpriceable suppression fix suppresses $40K Treasury bond notional from cash replay (3 txns). Previously showed +1.21% due to daily TWR amplification of unpriceable bond trades.
- **Schwab** still broken: +17.53% vs -8.29% actual. Per-account 165 (-8.30%) and 013 (-14.73%) are near-perfect. Aggregated rollup distorted by account 252 (tiny $21 starting balance + $46K deposits = extreme TWR sensitivity).
- **Combined** at +25.04%, pulled up by Schwab's aggregated distortion. IBKR and Plaid are both within ~1pp of actual.
- **Performance concern**: IBKR/Combined runs take ~90-95s. Plaid 13s, Schwab 18s. The 6,598-line analysis file needs profiling.

---

## What Each Fix Did

### Pre-P1 Baseline (observed-only track selected by sensitivity gate)
- `source=all`: -64.37% total (March 2025: -73.63% from futures notional)
- Used observed-only track because sensitivity gate fired ($67K gap)
- 27 synthetic entries, 3 unpriceable symbols (MGC, ZF, US Treasury Note)
- V_adjusted <= 0 for many months (2024-05 through 2024-09)

### 1. P1: UNKNOWN/fx_artifact filtering + futures inference gating (`efd8f1a6`)

- **Plan**: `docs/planning/completed/CASH_REPLAY_P1_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `derive_cash_and_external_flows()`
- Filtered UNKNOWN-symbol Plaid trades ($4M phantom volume)
- Filtered fx_artifact symbols (GBP.HKD, USD.HKD)
- Gated inference during open futures exposure
- **Effect**: Flipped combined from -64% to +84% (sensitivity gate now selects enhanced track differently)
- IBKR: +126%, Schwab: +143%, Plaid: +1%

### 2. P2A: Synthetic cash excluded from replay + diagnostic-only gate (`eb9fc423`)

- **Plan**: `docs/planning/completed/CASH_REPLAY_P2_SYNTHETIC_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — line 3076 (`transactions_for_cash = fifo_transactions`) + removed sensitivity gate track-switch block (lines 3990-4026)
- Removed `synthetic_cash_events` from `transactions_for_cash` (one-line fix)
- Made SYNTHETIC_PNL_SENSITIVITY gate diagnostic-only (no more track switching)
- **Effect**: Combined went +84% → +188% (enhanced track always used now)
- IBKR improved dramatically: +126% → -69% (closer to -9% actual)
- Schwab: +143% → +51%
- Plaid: +1% → -8% (very close to -12% actual)

### 3. Source attribution hardening + reliability diagnostics (`c6b45489`)

- **Plan**: Phase-1 remediation / realized data-quality workstream
- **Implementation**: `core/realized_performance_analysis.py`, tests, baseline fixtures
- Source attribution hardening, reliability diagnostics, MCP/source-scoped behavior
- Tests + baseline fixture updates

### 4. Observed-only NAV branch fix (`b503cf76`)

- **Plan**: `docs/planning/completed/CASH_REPLAY_P2_FIX_PLAN.md` + remediation plan doc
- **Implementation**: `core/realized_performance_analysis.py` — observed-only NAV replay
- Observed-only NAV branch now excludes provider-authoritative flows
- Added regression coverage for observed-vs-provider NAV impact

### 5. P2B: Futures fee-only + income/provider dedup + P3 plan (`1d943108`)

- **Plan**: `docs/planning/completed/CASH_REPLAY_P2_FIX_PLAN.md` (Workstreams A, B, C)
- **Implementation**: `core/realized_performance_analysis.py` — `derive_cash_and_external_flows()`, metadata, result objects
- Futures BUY/SELL cash impact reduced to fee-only (suppressed $519K notional)
- Income/provider-flow overlap dedup (dropped 40 duplicate rows, -$1,178 net)
- Added metadata diagnostics: `futures_cash_policy`, `futures_notional_suppressed_usd`, `income_flow_overlap_*`
- Also includes post-P2B live test artifacts and P3 plan doc
- **Effect**: Commits 3-5 all landed before P3 measurement; their combined effect is captured in the "Post-P2B" column above

### 6. P3: Global inception + futures incomplete trade filter (`0e533cb7`)

- **Plan**: `docs/planning/completed/CASH_REPLAY_P3_TIMELINE_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `build_position_timeline()` line 1196 + futures filter after line 1253
- All `synthetic_current_position` entries now use global inception (no mid-period NAV jumps)
- Futures `synthetic_incomplete_trade` entries filtered from position timeline
- **Effect**: Combined +188% → -24% (huge improvement, right direction)
- **Regression**: IBKR -69% → -100% (removing futures phantom NAV exposed cash/position asymmetry)
- Schwab: +51% → +50% (minimal change)
- Plaid: -8% → -8% (no change, correct)

### 7. P3.1: Futures compensating events + incomplete trade synthetics at inception

- **Plan**: `docs/planning/completed/CASH_REPLAY_P4_INCOMPLETE_TRADE_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `build_position_timeline()`
- Two changes:
  1. **Futures compensating events**: For each filtered futures IncompleteTrade (MES, MGC, MHI), add a compensating +qty event at sell_date - 1s to balance the unmatched SELL. Position nets to 0 at month-end. Skips keys with current-position synthetics (already covered by `required_entry_qty = abs(shares) + exit_qty`).
  2. **Incomplete trade synthetics at inception**: Changed synthetic placement from `sell_date - 1s` to `inception_date - 1s` for all non-futures incomplete trades. Position value now exists from inception → SELL converts position to cash (roughly neutral for returns) instead of appearing as phantom cash.
- **Effect**: IBKR -100% → +10.45% (actual: -9.35%). Plaid/Schwab unchanged.
- Monthly returns now plausible: Mar -3.68%, Apr +1.41%, May-Jan in -1.37% to +5.32% range.

### 8. P3.2: Schwab cross-source attribution fix (native-over-aggregator tiebreaker)

- **Plan**: `docs/planning/completed/SCHWAB_CROSS_SOURCE_ATTRIBUTION_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `_provider_matches_from_position_row()` + `_build_source_scoped_holdings()`
- Two changes:
  1. **Row-level tiebreaker** (line 665): When `position_source="plaid,schwab"` (consolidated row), narrow SECONDARY matches to native sources only. Handles `consolidate=True` case.
  2. **Symbol-level leakage exemption** (line 733): When a symbol appears in both native (schwab) and aggregator (plaid) rows, exempt from leakage when requesting native scope. The aggregator is mirroring the native account — not genuine cross-source exposure. Guards: requires exactly 1 native source, no unknown sources, requesting scope must be the native source.
- **Effect**: Schwab +49.76% → +33.13% (actual: -8.29%). DSU/MSCI/STWD ($82K, 66% of portfolio) now included in Schwab scope. Monthly returns moderated from +11-13% to +6-9% in peak months. IBKR/Plaid unchanged.

### 9. Schwab Fixes A/E/F/G: Per-account aggregation + cash-back/timestamp/inception + system transfers

- **Plan**: `docs/planning/SCHWAB_RETURN_GAP_INVESTIGATION.md`
- **Implementation**: `core/realized_performance_analysis.py` — per-account aggregation, cash-back timestamp fix, inception deferral, per-symbol synthetic inception, system transfer BUY + contribution
- Four changes:
  1. **Fix A**: Per-account aggregation — run realized perf per-account then aggregate monthly series. Eliminates cross-account synthetic backdating.
  2. **Fix E**: Cash-back timestamp + inception deferral for accounts with only returns/dividends (no buys).
  3. **Fix F**: Per-symbol synthetic inception (defensive).
  4. **Fix G v2**: System transfer BUY + contribution recognition.
- **Effect**: Schwab +33.13% → +23.13%. Plaid -7.96% → -12.93% (closer to actual). IBKR regressed +10.45% → -71.78% (side-effect: extreme month filter now fires on IBKR).

### 10. Remove Extreme Month Exclusion Filter

- **Plan**: `docs/planning/completed/REMOVE_EXTREME_MONTH_FILTER_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — deleted `extreme_month_filter_active` gate, NaN-ification branch, and `EXTREME_MONTHLY_RETURNS_EXCLUDED` flag. Deleted corresponding test.
- The filter was introduced in commit `25165d7c` as a band-aid for pre-P1 data quality bugs. After P1-P3.2 + Schwab fixes, the extreme returns that remain are structurally expected artifacts of incomplete transaction history — not bugs. The cost-basis flow injection plan will address them properly.
- **Effect**: IBKR -71.78% → +15.27% (March 2025 +308% restored to chain-linking). Schwab/Plaid/Combined unchanged.

### 11. Fix H: Daily TWR implementation (`4adb8176`)

- **Plan**: `docs/planning/SCHWAB_RETURN_GAP_INVESTIGATION.md`
- **Implementation**: `core/realized_performance_analysis.py` — added `compute_twr_monthly_returns()` daily chain-link function
- Switched from monthly Modified Dietz to daily TWR for intra-month sub-period accuracy
- **Effect**: Improved per-account Schwab accuracy. Headline aggregated numbers unchanged.

### 12. Fix I: GIPS BOD TWR formula + CASH_RECEIPT date alignment (`794623d1`)

- **Plan**: `docs/planning/completed/GIPS_BOD_TWR_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — rewrite TWR inner loop to GIPS BOD method; `providers/flows/schwab.py` — use `time` for CASH_RECEIPT rows
- Two changes:
  1. **BOD method**: Use `V_{D-1}` instead of `day_nav - flow` for pre-flow sub-period end
  2. **CASH_RECEIPT date**: Use `time` (actual receipt) instead of `tradeDate` (T+1 settlement)
- **Effect**: Account 013 gap: +11pp → 0.05pp. Headline aggregated numbers unchanged.

### 13. Fix J: Futures daily MTM settlement (`3ce88f1c`)

- **Plan**: `docs/planning/completed/FUTURES_MTM_SETTLEMENT_PLAN.md`
- **Implementation**: `ibkr/flex.py` — parse StmtFunds section for daily MTM; `core/realized_performance_analysis.py` — new `FUTURES_MTM` event type in cash replay
- Root cause: IBKR accounts for futures via daily mark-to-market cash settlement (commodities column = $0 in EquitySummaryInBase). Our system only captured commissions (~$40), missing all actual P&L (e.g., MHI -$30K Hang Seng crash Apr 7).
- Three-layer fix:
  1. **Parse**: `normalize_flex_futures_mtm()` extracts Position MTM rows from StmtFunds, deduplicates currency-segment duplicates
  2. **Thread**: `ibkr_flex_futures_mtm` key through data_fetcher → ibkr_transactions → analyzer
  3. **Consume**: `FUTURES_MTM` event type in `derive_cash_and_external_flows()` — TYPE_ORDER priority 5 (after BUY/COVER), `is_futures=False` to bypass trade branch, mixed-authority partitioning
- **Effect**: IBKR +15.71% → **-11.37%** (broker: -9.35%). Gap: **25pp → 2pp**. March +308% spike eliminated. Schwab/Plaid unchanged.

### 14. IBKR Flex Phase 2 Polling Fix (`f4dac23f`)

- **Implementation**: `ibkr/flex.py` — fixed Phase 2 polling to correctly fetch StmtFunds + additional topics
- **Effect**: IBKR **-11.37% → +111.42%** (massive regression). Root cause: two bugs exposed by the additional data — StmtFunds topic name wrong + ghost account in per-account aggregation.

### 15. StmtFunds Topic Name Fix (`fe297eda`)

- **Plan**: `docs/planning/completed/GHOST_ACCOUNT_FIX_PLAN.md`
- **Implementation**: `ibkr/flex.py` lines 1103, 1114 — `"StmtFunds"` → `"StatementOfFundsLine"` (the actual XML element tag)
- The Phase 2 polling fix exposed that the topic name was wrong. Container tag is `<StmtFunds>`, but data element tag (used by `_extract_rows()`) is `<StatementOfFundsLine>`. 564 raw rows → 105 normalized MTM events with -$42,945 total cash impact now flowing correctly.
- **Effect**: Part of combined fix with #16 below.

### 16. Ghost Account Filtering (`264c2940`)

- **Plan**: `docs/planning/completed/GHOST_ACCOUNT_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — new `_looks_like_display_name()` helper + updated `_discover_account_ids()`
- Root cause: SnapTrade positions report `account_name="Interactive Brokers (Henry Chien)"` while Flex transactions use `account_id="U2471778"`. Same account, different identifiers → 2-account aggregation. The ghost account matched 0 transactions → synthetic-only analysis → March +641%.
- Fix: position-only accounts that look like display names (contain institution keyword, parentheses, or long names) are filtered when transaction-derived accounts exist. Real account IDs (IBKR U-numbers, Schwab masked) are never filtered.
- 12 new tests in `tests/core/test_discover_account_ids.py`.
- **Effect**: Fixes #15 + #16 combined: IBKR **+111.42% → -32.53%** (broker: -9.35%). Ghost account eliminated, MTM flowing correctly. But still ~23pp off due to 19 synthetic positions creating TWR distortion.

### 17. Synthetic TWR Flow Fix (`12966d69`)

- **Plan**: `docs/planning/SYNTHETIC_TWR_FLOW_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — new `_synthetic_events_to_flows()` helper + TWR wiring + `_postfilter` storage
- Root cause: 19 synthetic positions (first-transaction-exits) appeared in NAV but their cash events were excluded from TWR external flows. The GIPS formula interpreted NAV jumps as returns (+490% March) instead of contributions.
- Three changes:
  1. **Helper**: `_synthetic_events_to_flows()` converts synthetic cash events to TWR flow tuples. BUY → positive inflow, SHORT → negative outflow.
  2. **TWR wiring**: `twr_external_flows = external_flows + synthetic_twr_flows` passed to `compute_twr_monthly_returns()`.
  3. **Aggregation**: `_postfilter["external_flows"]` stores `twr_external_flows` so aggregation path picks up synthetic flows.
- Modified Dietz path unchanged — the cash replay exclusion was correct for that formula.
- 11 new tests in `tests/core/test_synthetic_twr_flows.py`. 145 existing tests pass.
- **Effect**: IBKR **-32.53% → -24.80%** (~8pp improvement toward -9.35% actual). Schwab/Plaid unchanged.

### Current State (after fix 20, measured 2026-03-03, re-measured 2026-03-08)

**WARNING — Baseline shift detected (fix 18→19).** After measuring fix 19, IBKR and Schwab numbers shifted significantly from fix 18 measurements taken earlier the same day. Likely causes: (1) IBKR analysis period now starts at 2025-04-30 (was Feb 2025), (2) futures notional amplification in earlier months creating March +292% spike. **Fresh broker statements needed to establish a new comparison baseline for a specific time period.**

| Source | Return (fix 18) | Return (fix 20) | 2026-03-07 | 2026-03-08 | Broker Actual | Notes |
|--------|-----------------|-----------------|------------|------------|---------------|-------|
| **IBKR Flex** | -8.04% | -77.69% | +2.60% | **-0.19%** | +0.29% (statement) | **0.48pp** ✅ Dual cash anchor working |
| **Schwab (agg)** | +17.53% | +21.94% | +5.09% | **+9.70%** | ~+5.6% (weighted) | **~4.1pp** ❌ Regressed. snaptrade_cur anchor $65,945 distorting |
| **Schwab 165** | -8.30% | — | -8.32% | **-7.35%** | -8.29% | 0.94pp (was 0.03pp) |
| **Schwab 252** | +273.92% | +0.82% | +9.55% | **+13.13%** | +10.65% | 2.48pp (was 1.10pp) |
| **Schwab 013** | -14.73% | — | -3.20% | **+2.36%** | -14.69% | 17.05pp ❌ (further regressed) |
| **Plaid (Merrill)** | -11.77% | -11.77% | — | **-11.36%** | -12.49% | 1.13pp ✅ |

**Schwab aggregate comparison correction (2026-03-07):** The -8.29% "broker actual"
used previously was account 165's individual return, not an aggregate. Account 252
(~$66K, 74% weight) dominates the aggregate. The proper NAV-weighted broker aggregate
is ~+5.6%: `($66K × 10.65% + $21K × -8.29% + $2K × -14.69%) / $89K`. Our engine's
+5.09% is **only ~0.5pp off** from the correct broker aggregate. The Schwab aggregate
was never broken — the comparison target was wrong.

---

### 18. Synthetic TWR Price Alignment (`7104de8c`)

- **Plan**: `docs/planning/SYNTHETIC_TWR_PRICE_ALIGNMENT_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `_synthetic_events_to_flows()` now accepts `price_cache`, uses `_value_at_or_before()` for NAV-aligned pricing
- Root cause: Synthetic TWR flows used sell prices from incomplete trades, but NAV values positions at market prices from `price_cache`. Example: CBL sell price $22.87 vs market price $31.27 — $840 gap per position. Total mismatch ~$3K (12% of portfolio) across 7 tickers.
- Fix: `_synthetic_events_to_flows()` looks up `price_cache` via `_value_at_or_before()` (same function used by `compute_monthly_nav()`). Falls back to event price if no cache entry.
- 4 new tests (15 total in `test_synthetic_twr_flows.py`). 145 existing tests pass.
- **Effect**: IBKR **-24.80% → -8.04%** (~17pp improvement). Gap to broker: **15.45pp → 1.31pp**. Remaining gap consistent with period mismatch (system: Mar '25–Feb '26 vs broker: calendar 2025). Schwab/Plaid unchanged.

### 19. Flow-Date Snapping in Aggregate Inception Filter (`99b30bfc`)

- **Plan**: `docs/planning/FLOW_DATE_SNAPPING_FIX_PLAN.md` (Codex-reviewed, PASS after R3+R6 addressed)
- **Implementation**: `core/realized_performance_analysis.py` — new `_snap_flow_date_to_nav()` helper + fixed flow filter in `_sum_account_daily_series()`
- Root cause: `_sum_account_daily_series()` inception filter (`min_inception_nav=500`) compares raw flow dates against `first_viable` (always a business day). Flows on weekends/holidays get dropped even though `compute_twr_monthly_returns()` would snap them to the next business day. Concrete case: Account 165's $18,342 inception deposit on **Saturday Aug 24** dropped because `Aug 24 < first_viable (Monday Aug 26)`. The aggregate sees $19K starting NAV with no matching inflow — $18K of "free capital" inflating returns by ~14pp.
- Fix: `_snap_flow_date_to_nav()` replicates `searchsorted(side="left")` logic from TWR engine. Flow filter now snaps dates before comparing against `first_viable`. `full_nav_idx` captured before slicing `nav_s`.
- 3 new tests (18 total in `test_synthetic_twr_flows.py`). 163 existing tests pass.
- **Effect**: Could not verify — baseline numbers shifted between sessions (see Current State warning above). Fix is logically correct for weekend/holiday inception flows near `first_viable`.

### 20. Schwab RECEIVE_AND_DELIVER as Position Exit

- **Plan**: `docs/planning/SCHWAB_RECEIVE_DELIVER_FIX_PLAN.md` (Codex-reviewed, PASS after R1-R14 addressed across 4 rounds)
- **Implementation**: `providers/normalizers/schwab.py` — shared `_resolve_receive_deliver()` helper + `_is_trade_candidate()` update + dedicated main loop path; `providers/flows/schwab.py` — bidirectional flow emission using shared helper
- Root cause: Schwab `RECEIVE_AND_DELIVER` transactions were silently skipped by the normalizer (`_is_trade_candidate()` returned False). Account 252 bought 4 GLBE shares (Aug-Oct 2024), transferred them out via RECEIVE_AND_DELIVER on Oct 17. No exit event in position_timeline → phantom GLBE valued at market price indefinitely → GLBE's ~60% Nov rally produced impossible +103% monthly return on ~$80 cash base → compounds to +274%.
- Four changes:
  1. **Shared helper** `_resolve_receive_deliver()`: resolves action/quantity/price/instrument from first non-currency transfer leg. closingPrice fallback for price=0. Multi-leg warning. Used by both normalizer and flow parser (guarantees identical leg selection).
  2. **Trade candidate recognition**: `_is_trade_candidate()` now returns `(True, action)` for RECEIVE_AND_DELIVER.
  3. **Dedicated normalizer path**: RECEIVE_AND_DELIVER checked by family (not action) before standard trade path. Uses helper output exclusively. Does not skip on price=0 (phantom position is worse).
  4. **Cash-neutral flow emission**: Outbound SELL → matching withdrawal. Inbound BUY → matching contribution. Symmetric with existing System Transfer BUY → contribution pattern.
- Also: RECEIVE_AND_DELIVER excluded from `_build_trade_description_map()`.
- **Effect**: Account 252 **+273.92% → +0.82%** (broker: +10.65%). Schwab aggregate **+22.13% → +21.94%** (marginal — 252 is tiny relative to aggregate after $65K deposit). IBKR/Plaid unchanged.

---

## Remaining Distortion Analysis

### IBKR: ✅ nearly solved — -0.19% vs +0.29% (0.48pp)

Dual cash anchor implementation closed the gap from 2.31pp to **0.48pp**. The
statement-level starting/ending cash (`extract_statement_cash()`) now anchors the
NAV reconstruction at known points, eliminating fake contribution inference.

Previous -77.69% regression (fix 19 measurement) was resolved by the dual cash
anchor work. See `IBKR_REALIZED_PERF_COMPARISON.md` and `DUAL_CASH_ANCHOR_PLAN.md`.

### Schwab: TWR returns accurate, NAV P&L diagnostic diverges

**TWR headline returns are reliable.** Apples-to-apples comparison (pre-fix vs
post-fix for account 165) confirmed monthly TWR returns are identical — the
0.94pp gap is structural, not a regression. The 110.9% recon gap is purely a
Modified Dietz NAV P&L diagnostic issue (NAV P&L = -$19,872 vs lot P&L = -$276),
not a headline return accuracy problem.

**Investigation findings (2026-03-08):**
- The `USD:CASH -$16,532` anchor row correctly belongs to Schwab account 252
  (`position_source=schwab`). Not a cross-institution leak.
- Account 165 has 0 provider-authoritative flow events (only TRADE +
  DIVIDEND_OR_INTEREST txn types; no ACH/CASH_RECEIPT). Coverage window
  (Mar 2025+) post-dates the 9 synthetic inception events (Aug 2024).
- The `external_net_flows` change ($0.04 → $18,342) between sessions is from
  the TWR inception fix affecting the Modified Dietz denominator, not TWR.

Per-account (full period, Mar 8):
- **252: +13.13% vs +10.65% (2.48pp)** — structural pricing/methodology gap (see below).
- **165: -7.35% vs -8.29% (0.94pp)** — TWR accurate. NAV P&L is diagnostic artifact.
- **013: +2.36% vs -14.69% (17.05pp)** — tiny $2K account, cash anchor denominator
  sensitivity on $90 base. Low priority (2% of aggregate weight).

**Account 252 deep-dive (2026-03-08):**

Data quality is clean — 100% coverage, 0 synthetic positions, income dedup exact
($0.00 delta vs DB). The 2.48pp gap is structural, not a data quality issue:

- **Income verified**: $5,637 total ($6,852 dividends - $1,215 margin interest).
  DB has 3x duplicate rows per event; engine dedupes perfectly.
- **UNRESOLVED_DIVIDEND ($772) = ENB**: Quarterly Enbridge dividends ($148-$160/qtr)
  that the Schwab normalizer can't resolve. Legitimate income — broker counts it too.
- **External flows correct**: Cash Back Rewards (small, ~$25-73) + bank transfers
  (large, $700-$65K). No dividend misclassification. $65K CASH_RECEIPT on Jan 30, 2025
  falls outside coverage window (Mar 2025+), absorbed into starting cash via anchor.
- **Starting NAV ($65,152) verified**: Consistent with $65K cash → stock deployment
  Jan-Feb 2025. Cash anchor backsolve matches the trade/flow/income arithmetic.
- **Gap sources investigated and resolved**:
  - (a) ~~FMP adjusted vs market pricing~~ **RULED OUT**: Engine uses unadjusted `close`
    from FMP `historical_price_eod` endpoint. That endpoint doesn't have `adjClose` at all.
  - (b) ~~ENB DRIP fractional buys not in FIFO~~ **RULED OUT**: 5 quarterly DRIP buys
    totaling $115.86 missing from FIFO, but excess cash ($115.86) exactly offsets missing
    ENB shares (~2.2 × $53). Net NAV impact = **$0.00**.
  - (c) **Return methodology difference**: Schwab uses XIRR (money-weighted IRR), engine
    uses TWR (chain-linked daily). Engine TWR=13.13%, engine MWR=8.58%, broker=10.65%.
    The TWR/XIRR divergence accounts for ~2-4pp depending on flow timing.
  - (d) **Position pricing source**: XIRR sensitivity analysis shows broker's 10.65%
    implies ending NAV of ~$53,053 vs engine's $54,404 — a **$1,351 (2.5%)** position
    pricing difference between FMP and Schwab's data sources.
  - (e) Period boundaries (engine: month-end vs broker: calendar day) — minor contributor.
- **No actionable fix**: Gap is a combination of TWR vs XIRR methodology and FMP vs
  Schwab position pricing. Not a bug — would require switching pricing sources to close.

### Plaid: -11.77% (actual: -12.49%) — 0.72pp off ✓

Previously showed +1.21% (inverted sign). The unpriceable symbol suppression fix (commit `8829bb2f`) resolved the daily TWR amplification from the US Treasury Note (priced at $0, $40K notional suppressed across 3 txns). Now within 0.72pp of actual. Remaining gap likely from 1 synthetic position (IT, $3.4K) and 0% trade coverage. Still flagged unreliable due to low coverage.

---

## Diagnostic Summary

| Metric | Pre-P1 | Post-P1 | Post-P2B | Post-P3 | Post-P3.1 | Post-P3.2 | Post-Schwab fixes | Post-Filter removal |
|--------|--------|---------|----------|---------|-----------|-----------|-------------------|---------------------|
| Synthetic entry count | 27 | ~27 | ~24 | ~22 | 22 | 22 | 24 (Plaid) / 0 (Schwab) / 6 (IBKR) | same |
| Extreme months excluded | 1 | varies | varies | 0 | 0 | 0 | 1 (IBKR Mar +308%) | **0** |
| V_adjusted<=0 months | 5+ | varies | 0 | 8 (IBKR) | 0 | 0 | 0 | 0 |
| Unpriceable symbols | 3 | 1 | 1 | 1 | 2 | 2 | 2 | 2 |
| Track used | Observed-only | Enhanced | Enhanced | Enhanced | Enhanced | Enhanced | Enhanced (Plaid: obs-only) | same |
| Schwab leakage symbols | N/A | N/A | N/A | 3 | 3 | 0 | 0 | 0 |

---

## Attempted & Reverted

### Cost-Basis Flow Injection (attempted 2026-03-01, reverted)

- **Plan**: `docs/planning/SYNTHETIC_INCEPTION_FLOW_FIX_PLAN.md`
- **Implementation**: Codex-implemented, passed code review + 155 unit tests
- **Result**: Reverted. IBKR barely moved (-0.07pp), Plaid regressed 14pp, Schwab improved 5.6pp as side-effect of price priority flip. The flow injection seeds the Modified Dietz denominator but doesn't fix the V_start=0 → large NAV jump problem (the injected flows are too small relative to the NAV swing). The price priority flip (`price_hint` before FMP in `_create_synthetic_cash_events`) had unintended side-effects on all sources.

### Per-Symbol Inception for All Sources (attempted 2026-03-02, reverted `d9a9f886`)

- **Plan**: `docs/planning/PER_SYMBOL_INCEPTION_PLAN.md`
- **Implementation**: Changed `use_per_symbol_inception` from Schwab-only to all sources (default True).
- **Result**: Reverted. IBKR went from -32.53% to **+3,934%** (+30,261% best month). With per-symbol inception, synthetics appear one-by-one throughout March, each creating individual daily NAV spikes in TWR. The fix was worse than the disease — individual spikes are harder to neutralize than a single inception-day batch.
- **Lesson**: The real fix is to include synthetic cash events as TWR flows (neutralize the NAV jump), not to move the synthetics to different dates.

### TWR Inception Deferral (attempted 2026-03-02, reverted `deb9495b`)

- **Plan**: `docs/planning/TWR_TINY_BASE_DEFERRAL_PLAN.md`
- **Implementation**: `_defer_inception()` helper slices `daily_nav` + `external_flows` to start from first day NAV >= $500.
- **Result**: Reverted. Band-aid that hid the tiny-base phase rather than fixing the real problem (phantom GLBE position from unhandled RECEIVE_AND_DELIVER). Also had a bug: deferred `external_flows` but `twr_external_flows` (used at line 4621 and stored in `_postfilter`) remained un-deferred.

### Remove min_inception_nav Filter (attempted 2026-03-03, reverted `6742f471`)

- **Plan**: `docs/planning/REMOVE_INCEPTION_NAV_FILTER_PLAN.md`
- **Implementation**: Removed `min_inception_nav=500` filter from `_sum_account_daily_series()` and `_sum_account_monthly_series()`.
- **Result**: Reverted. Let account 252's $11 NAV flow into aggregate from inception, but phantom GLBE returns (+39%/+103% monthly) still compound. The filter was masking the symptom; the root cause is the unhandled RECEIVE_AND_DELIVER.

### P5: V_start Seeding (attempted earlier, reverted)

IBKR regressed to -47% because synthetic `price_hints` are unreliable for 21 positions.

## Next Steps

### Immediate: Establish New Baseline

Numbers shifted between sessions (IBKR -8.04% → -77.69%, Schwab +17.53% → +22.13%). Before further fixes, need to:

1. **Re-download broker statements** for a specific comparison period (e.g., calendar 2025 or a shorter window) to get fresh ground truth
2. **Build a cleaner data ingestion process**: explicitly put in trades, mark flows, normalize — better visibility into raw data before evaluating synthetics/calculations. Current approach of running the full pipeline and comparing headline numbers makes it hard to isolate where distortion enters.
3. **Investigate IBKR analysis period shift**: why does it now start at 2025-04-30 instead of Feb 2025? Is this a data availability issue (Flex query window)?
4. **Investigate Plaid returning None**: was working before, now returns no result

### Per-Source Status (updated 2026-03-08)

- **IBKR**: ✅ **Solved.** -0.19% vs +0.29% statement actual (**0.48pp gap**). Dual cash anchor working.
- **Plaid (Merrill)**: ✅ **Solved.** -11.36% vs -12.49% actual (**1.13pp gap**).
- **Schwab 165**: ✅ **Solved.** -7.35% vs -8.29% (**0.94pp**). TWR returns accurate. 110.9% recon gap is a Modified Dietz NAV P&L diagnostic artifact, not a headline return issue.
- **Schwab 252**: ⚠️ +13.13% vs +10.65% (**2.48pp**). TWR vs XIRR methodology + FMP vs Schwab position pricing ($1,351 / 2.5% NAV diff). All hypotheses investigated: FMP uses unadjusted close (ruled out), ENB DRIP NAV-neutral (ruled out). Not fixable without switching pricing sources.
- **Schwab 013**: ⚠️ +2.36% vs -14.69% (**17pp**). Tiny $2K account (2% weight). Cash anchor denominator sensitivity. Low priority.
- **Schwab aggregate**: ⚠️ +9.70% vs ~+5.6% (**4.1pp**). Pulled by 252 gap. TWR aggregate composition effect.
- **Performance**: Combined/IBKR runs take ~90-95s. Need profiling to identify hot path.
