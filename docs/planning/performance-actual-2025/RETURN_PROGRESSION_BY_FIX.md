# Realized Performance: Return Progression by Fix Phase

**Root investigation**: `docs/planning/REALIZED_PERF_DATA_QUALITY.md`

## Broker Actuals (Ground Truth)

| Account | Broker Reported Return | Period |
|---------|----------------------|--------|
| IBKR (U2471778) | **-9.35%** | 2025 YTD |
| Schwab (main) | **-8.29%** | 2024-04 to 2025-12 |
| Merrill Edge (Plaid) | **-12.49%** | 2024-01 to 2025-12 |

Sources: `baseline_extracted_data.json`, broker statements in `performance-actual-2025/`

---

## Total Return Progression

| Source | Baseline (pre-P1) | After #1 P1 | After #2-#5 (P2A+P2B) | After #6 P3 | After #7 P3.1 | After #8 P3.2 | Broker Actual |
|--------|-------------------|-------------|------------------------|-------------|---------------|---------------|---------------|
| **Combined** | -64.37% | +83.91% | +188.08% | -23.84% | +34.66% | **+34.66%** | -8 to -12% |
| **IBKR Flex** | (in combined) | +126.32% | -68.88% | -100.00% | +10.45% | **+10.45%** | -9.35% |
| **Schwab** | (in combined) | +142.79% | +51.36% | +49.76% | +49.76% | **+33.13%** | -8.29% |
| **Plaid (Merrill)** | (in combined) | +1.32% | -7.96% | -7.96% | -7.96% | **-7.96%** | -12.49% |

Column mapping:
- **Baseline**: Before any fixes. Observed-only track (sensitivity gate fired).
- **After #1 P1** (`efd8f1a6`): UNKNOWN/fx filtering + futures inference gating.
- **After #2-#5** (`eb9fc423` → `1d943108`): P2A synthetic cash exclusion + diagnostic-only gate + source attribution hardening + observed-only branch fix + P2B futures fee-only + income dedup.
- **After #6 P3** (`0e533cb7`): Global inception + futures incomplete trade filter.
- **After #7 P3.1** (`6c2f6e89`): Futures compensating events + incomplete trade synthetics at inception.
- **After #8 P3.2**: Schwab cross-source attribution fix (native-over-aggregator tiebreaker).

### Key observations

- **Plaid** is the closest to actual (-7.96% vs -12.49%), stable since commits #2-#5.
- **IBKR** dramatically improved: -100% → +10.45% after P3.1 (#7). Two fixes: (1) compensating events balance futures SELL transactions that lost their synthetic openings in P3, (2) incomplete trade synthetics placed at inception instead of sell_date - 1s so SELL cash is a position-to-cash conversion, not phantom cash.
- **Schwab** improved: +49.76% → +33.13% after P3.2 (#8). The cross-source attribution fix included DSU/MSCI/STWD (66% of portfolio, $82K) that were previously excluded because the same symbols appeared in both Schwab and Plaid (Merrill mirror). The remaining +33% distortion is from 6 synthetic positions (PCTY, DSU, GLBE, MSCI, CPPMF, LIFFF) that enter at inception with current price hints — any appreciation since Apr 2024 inception shows as returns.
- **Combined** at +34.66%, still pulled up by Schwab's +33%. IBKR and Plaid are both in reasonable range.

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

---

## Remaining Distortion Analysis

### IBKR: +10.45% (actual: -9.35%) — ~20pp off

The IBKR return is now in the right ballpark but still ~20pp too high. Remaining factors:
- 2 unpriceable futures symbols (MGC, ZF) — IBKR fallback not running, positions may be mispriced
- Incomplete trade `price_hint` (sell_price used as proxy for inception value) may overstate position value at inception
- 45% data coverage means many months have limited position data

Monthly returns (post-P3.1):
- Mar 2025: -3.68%
- Apr 2025: +1.41%
- May-Jan: range -1.37% to +5.32% (all plausible)

### Schwab: +33.13% (actual: -8.29%) — ~41pp off

Root cause: **6 synthetic positions with significant appreciation**

After P3.2, DSU and MSCI are now in Schwab scope (previously excluded). The 6 synthetic positions (CPPMF, DSU, GLBE, LIFFF, MSCI, PCTY) with combined market value of $42K enter the position timeline at global inception (Apr 2024) with current `price_hint`. Any appreciation since inception shows as returns.

Monthly returns (post-P3.2):
- Jul 2024: +8.98%, Aug: +5.98%, Nov: +7.85% (PCTY rally, now diluted by larger base)
- Jan 2025 onwards: ±0-4% (reasonable after $65K contribution normalizes base)

The distortion is fundamentally a synthetic position accuracy problem — the `price_hint` at inception overestimates position value for positions that have depreciated and underestimates for positions that have appreciated. This creates a bias toward showing gains.

### Combined: +34.66% (actual: -8 to -12%)

Dragged up by Schwab's +33% distortion. IBKR and Plaid are both now in reasonable range.

---

## Diagnostic Summary

| Metric | Pre-P1 | Post-P1 | Post-P2B | Post-P3 | Post-P3.1 | Post-P3.2 |
|--------|--------|---------|----------|---------|-----------|-----------|
| Synthetic entry count | 27 | ~27 | ~24 | ~22 | 22 | 22 |
| Extreme months excluded | 1 | varies | varies | 0 | 0 | 0 |
| V_adjusted<=0 months | 5+ | varies | 0 | 8 (IBKR) | 0 | 0 |
| Unpriceable symbols | 3 | 1 | 1 | 1 | 2 | 2 |
| Track used | Observed-only | Enhanced | Enhanced | Enhanced | Enhanced | Enhanced |
| Schwab leakage symbols | N/A | N/A | N/A | 3 | 3 | 0 |

---

## Next Steps

**P5: V_start Seeding + Budget-Based Incomplete Trade Suppression** (`docs/planning/CASH_REPLAY_P5_VSTART_SEEDING_PLAN.md`)

Two changes targeting the remaining Schwab +33% and IBKR +10% distortions:

1. **V_start seeding**: Seed `compute_monthly_returns()` with initial NAV at inception from pre-existing (synthetic) positions. Currently V_start is hardcoded to 0, so any synthetic position appreciation appears as free gains on zero invested capital. This is the primary driver of Schwab's +33% distortion.

2. **Budget-based incomplete trade cash suppression**: Suppress the unmatched portion of incomplete trade SELLs in the cash replay. Currently all SELL cash enters replay at full notional, even when FIFO couldn't match the SELL to a prior BUY. This creates unbalanced cash that distorts IBKR returns.

Acceptance gates: IBKR gap <= 10pp (from 20pp), Schwab gap <= 21pp (from 41pp), no source regresses > 5pp.

**Stream C: Output Gating** (design in `WORKSTREAM_PLANS.md`, not yet implemented)

When data quality is poor, add `reliable: bool` + `reliability_note` to agent snapshots. Coverage-based and synthetic-dominance gates.
