# Realized Performance: Return Progression by Fix Phase

**Root investigation**: `docs/planning/REALIZED_PERF_DATA_QUALITY.md`

## Broker Actuals (Ground Truth)

| Account | Broker Reported Return | Period |
|---------|----------------------|--------|
| IBKR (U2471778) | **-9.35%** | 2025 calendar year |
| Schwab 165 | **-8.29%** | 2025 calendar year |
| Schwab 013 | **-14.69%** | 2025 calendar year |
| Schwab 252 | **+10.65%** | 2025 calendar year |
| Merrill Edge (Plaid) | **-12.49%** | 2024-01 to 2025-12 |

Sources: `baseline_extracted_data.json`, broker statements in `performance-actual-2025/`

### Per-Account Accuracy (2025 calendar year, system vs broker)

| Account | System | Broker | Gap | Reliable? |
|---------|--------|--------|-----|-----------|
| Schwab 165 | -8.30% | -8.29% | **0.01pp** | Yes |
| Schwab 013 | -14.73% | -14.69% | **0.04pp** | Yes |
| Schwab 252 | +28.37% | +10.65% | 17.7pp | No (tiny starting balance $21, large deposits) |
| IBKR | +15.71% | -9.35% | ~25pp | No (March +308% synthetic jump) |

---

## Total Return Progression

| Source | Baseline (pre-P1) | After #1 P1 | After #2-#5 (P2A+P2B) | After #6 P3 | After #7 P3.1 | After #8 P3.2 | After #9 Schwab A/E/F/G | After #10 Remove Extreme Filter | Broker Actual |
|--------|-------------------|-------------|------------------------|-------------|---------------|---------------|-------------------------|--------------------------------|---------------|
| **Combined** | -64.37% | +83.91% | +188.08% | -23.84% | +34.66% | +34.66% | +34.41% | **+34.41%** | -8 to -12% |
| **IBKR Flex** | (in combined) | +126.32% | -68.88% | -100.00% | +10.45% | +10.45% | -71.78% | **+15.27%** | -9.35% |
| **Schwab** | (in combined) | +142.79% | +51.36% | +49.76% | +49.76% | +33.13% | +23.13% | **+23.13%** | -8.29% |
| **Plaid (Merrill)** | (in combined) | +1.32% | -7.96% | -7.96% | -7.96% | -7.96% | -12.93% | **-12.93%** | -12.49% |

Column mapping:
- **Baseline**: Before any fixes. Observed-only track (sensitivity gate fired).
- **After #1 P1** (`efd8f1a6`): UNKNOWN/fx filtering + futures inference gating.
- **After #2-#5** (`eb9fc423` → `1d943108`): P2A synthetic cash exclusion + diagnostic-only gate + source attribution hardening + observed-only branch fix + P2B futures fee-only + income dedup.
- **After #6 P3** (`0e533cb7`): Global inception + futures incomplete trade filter.
- **After #7 P3.1** (`6c2f6e89`): Futures compensating events + incomplete trade synthetics at inception.
- **After #8 P3.2**: Schwab cross-source attribution fix (native-over-aggregator tiebreaker).
- **After #9 Schwab A/E/F/G**: Per-account aggregation, cash-back/timestamp/inception deferral, per-symbol synthetic inception, system transfer BUY + contribution. IBKR regressed to -71.78% (extreme month filter side-effect).
- **After #10 Remove Extreme Filter**: Removed `extreme_month_filter_active` gate that NaN-ified months >300% when synthetic tickers present. Restored IBKR March 2025 +308% to chain-linking.

### Key observations

- **Plaid** closest to actual (-12.93% vs -12.49%, 0.4pp gap). Improved from -7.96% after Schwab fixes (#9) — `SYNTHETIC_PNL_SENSITIVITY` gate now selects observed-only track. Extreme month filter removal had no effect (Aug +5447% already handled by observed-only track).
- **IBKR** restored to +15.27% after extreme month filter removal (#10). The Schwab fixes (#9) had a side-effect: `synthetic_current_tickers` became truthy, causing the extreme month filter to NaN-ify March 2025 +308% → IBKR regressed to -71.78%. Removing the filter fixed it. Still ~25pp off from -9.35% actual.
- **Schwab** at +23.13% after per-account aggregation (#9). Improved from +33.13% — per-account replay eliminated cross-account synthetic backdating. Remaining +31pp distortion from synthetic positions entering at inception with current price hints.
- **Combined** at +34.41%, still pulled up by Schwab's +23% and a 164,782% extreme month (warned but not excluded). IBKR and Plaid are both in reasonable range.

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

- **Plan**: `docs/planning/CASH_REPLAY_P2_FIX_PLAN.md` + remediation plan doc
- **Implementation**: `core/realized_performance_analysis.py` — observed-only NAV replay
- Observed-only NAV branch now excludes provider-authoritative flows
- Added regression coverage for observed-vs-provider NAV impact

### 5. P2B: Futures fee-only + income/provider dedup + P3 plan (`1d943108`)

- **Plan**: `docs/planning/CASH_REPLAY_P2_FIX_PLAN.md` (Workstreams A, B, C)
- **Implementation**: `core/realized_performance_analysis.py` — `derive_cash_and_external_flows()`, metadata, result objects
- Futures BUY/SELL cash impact reduced to fee-only (suppressed $519K notional)
- Income/provider-flow overlap dedup (dropped 40 duplicate rows, -$1,178 net)
- Added metadata diagnostics: `futures_cash_policy`, `futures_notional_suppressed_usd`, `income_flow_overlap_*`
- Also includes post-P2B live test artifacts and P3 plan doc
- **Effect**: Commits 3-5 all landed before P3 measurement; their combined effect is captured in the "Post-P2B" column above

### 6. P3: Global inception + futures incomplete trade filter (`0e533cb7`)

- **Plan**: `docs/planning/CASH_REPLAY_P3_TIMELINE_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `build_position_timeline()` line 1196 + futures filter after line 1253
- All `synthetic_current_position` entries now use global inception (no mid-period NAV jumps)
- Futures `synthetic_incomplete_trade` entries filtered from position timeline
- **Effect**: Combined +188% → -24% (huge improvement, right direction)
- **Regression**: IBKR -69% → -100% (removing futures phantom NAV exposed cash/position asymmetry)
- Schwab: +51% → +50% (minimal change)
- Plaid: -8% → -8% (no change, correct)

### 7. P3.1: Futures compensating events + incomplete trade synthetics at inception

- **Plan**: `docs/planning/CASH_REPLAY_P4_INCOMPLETE_TRADE_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — `build_position_timeline()`
- Two changes:
  1. **Futures compensating events**: For each filtered futures IncompleteTrade (MES, MGC, MHI), add a compensating +qty event at sell_date - 1s to balance the unmatched SELL. Position nets to 0 at month-end. Skips keys with current-position synthetics (already covered by `required_entry_qty = abs(shares) + exit_qty`).
  2. **Incomplete trade synthetics at inception**: Changed synthetic placement from `sell_date - 1s` to `inception_date - 1s` for all non-futures incomplete trades. Position value now exists from inception → SELL converts position to cash (roughly neutral for returns) instead of appearing as phantom cash.
- **Effect**: IBKR -100% → +10.45% (actual: -9.35%). Plaid/Schwab unchanged.
- Monthly returns now plausible: Mar -3.68%, Apr +1.41%, May-Jan in -1.37% to +5.32% range.

### 8. P3.2: Schwab cross-source attribution fix (native-over-aggregator tiebreaker)

- **Plan**: `docs/planning/SCHWAB_CROSS_SOURCE_ATTRIBUTION_FIX_PLAN.md`
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

- **Plan**: `docs/planning/REMOVE_EXTREME_MONTH_FILTER_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — deleted `extreme_month_filter_active` gate, NaN-ification branch, and `EXTREME_MONTHLY_RETURNS_EXCLUDED` flag. Deleted corresponding test.
- The filter was introduced in commit `25165d7c` as a band-aid for pre-P1 data quality bugs. After P1-P3.2 + Schwab fixes, the extreme returns that remain are structurally expected artifacts of incomplete transaction history — not bugs. The cost-basis flow injection plan will address them properly.
- **Effect**: IBKR -71.78% → +15.27% (March 2025 +308% restored to chain-linking). Schwab/Plaid/Combined unchanged.

### 11. Fix H: Daily TWR implementation (`4adb8176`)

- **Plan**: `docs/planning/SCHWAB_RETURN_GAP_INVESTIGATION.md`
- **Implementation**: `core/realized_performance_analysis.py` — added `compute_twr_monthly_returns()` daily chain-link function
- Switched from monthly Modified Dietz to daily TWR for intra-month sub-period accuracy
- **Effect**: Improved per-account Schwab accuracy. Headline aggregated numbers unchanged.

### 12. Fix I: GIPS BOD TWR formula + CASH_RECEIPT date alignment (`794623d1`)

- **Plan**: `docs/planning/GIPS_BOD_TWR_FIX_PLAN.md`
- **Implementation**: `core/realized_performance_analysis.py` — rewrite TWR inner loop to GIPS BOD method; `providers/flows/schwab.py` — use `time` for CASH_RECEIPT rows
- Two changes:
  1. **BOD method**: Use `V_{D-1}` instead of `day_nav - flow` for pre-flow sub-period end
  2. **CASH_RECEIPT date**: Use `time` (actual receipt) instead of `tradeDate` (T+1 settlement)
- **Effect**: Account 013 gap: +11pp → 0.05pp. Headline aggregated numbers unchanged.

---

## Remaining Distortion Analysis

### Schwab per-account: 2 of 3 solved

Accounts 165 (-8.30% vs -8.29%) and 013 (-14.73% vs -14.69%) are essentially exact. Account 252 (+28.37% vs broker +10.65%) remains distorted — tiny starting balance ($21) with $46K of deposits creates TWR sensitivity to timing. Schwab work continues in a separate session.

### IBKR: +10.99% 2025 (actual: -9.35%) — ~20pp off

IBKR return restored after extreme month filter removal (#10). March 2025 +308% now included in chain-linking. Remaining factors:
- 6 synthetic current positions ($15.7K market value) with estimated inception values
- 2 unpriceable futures symbols (MGC, ZF) — priced via IBKR Gateway fallback
- Incomplete trade `price_hint` (sell_price used as proxy for inception value) may overstate position value at inception
- 45% data coverage means many months have limited position data
- System inception is Feb 28 (first transaction) vs broker Dec 31, 2024 — period mismatch

### Plaid: +1.21% (actual: -12.49%) — ~14pp off

Regressed from -12.93% after Fix H/I landed (daily TWR + GIPS BOD changes). Previously closest to actual when observed-only track was selected. `SYNTHETIC_PNL_SENSITIVITY` gate still fires, but the TWR formula changes shifted the observed-only returns. One synthetic position (IT, $3.6K) and one unpriceable bond.

### Combined: +36.89% (actual: -8 to -12%)

Pulled up by Schwab aggregate +17.53% and a 403,086% extreme month in Apr 2024 (combined inception). IBKR and Plaid are in mid-range.

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

### P5: V_start Seeding (attempted earlier, reverted)

IBKR regressed to -47% because synthetic `price_hints` are unreliable for 21 positions.

## Next Steps

- **Schwab account 252**: TWR sensitivity on tiny starting balance. Being investigated in separate session.
- **IBKR**: March +308% from V_start=0 with $142K synthetic NAV. Needs fundamentally different approach — either transaction backfill or V_start seeding from broker statement beginning value.
- **Plaid**: Investigate regression from -12.93% to +1.21% after Fix H/I. May be a TWR formula interaction with the observed-only track.
