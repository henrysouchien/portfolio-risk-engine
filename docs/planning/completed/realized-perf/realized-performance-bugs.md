# Realized Performance — Known Bugs & Issues

Catalog of open issues discovered during realized performance analysis.
Multiple investigation sessions contribute to this doc.

Last updated: 2026-02-17

---

## B-001: Global inception date used for all synthetic positions

**Severity:** HIGH
**Status:** Fixed (2026-02-13)
**Impact:** Inflates unrealized P&L by tens of thousands of dollars

**Resolution:** Implemented per-symbol inception dates in `build_position_timeline()`. Each synthetic entry now uses the earliest known transaction date for that specific symbol (offset by -1s), falling back to global `inception_date` only for positions with zero transaction history. See `earliest_txn_by_symbol` logic in `core/realized_performance_analysis.py` lines ~371-377.

**Original description:**
`build_position_timeline()` derived a single `inception_date` (the earliest transaction across ALL symbols — currently 2022-08-18) and used it as the synthetic entry date for every position missing opening history. Positions purchased years later got a 2022 cost basis, massively distorting unrealized P&L.

**File:** `core/realized_performance_analysis.py` — `build_position_timeline()`

---

## B-002: Positions with zero transaction history (100% synthetic)

**Severity:** HIGH
**Status:** Mostly Fixed (2026-02-13) — cost basis now back-solved from broker data
**Impact:** These positions have completely fabricated cost bases; unrealized P&L is meaningless for them

**Resolution:** Two-pass FIFO with back-solved cost basis now uses broker-reported `cost_basis` to compute pre-window entry prices for positions with partial or no transaction history. `_build_seed_open_lots()` computes `pre_window_cost = broker_cost_basis - observed_lot_cost` and seeds the FIFO matcher with initial open lots at the correct cost. FX-aware for non-USD positions.

**Remaining gap:** Positions where broker API returns no `cost_basis` (e.g., CPPMF) still fall back to FMP inception price. Backfill JSON can be used for manual overrides.

**Affected tickers:** CPPMF, IGIC, KINS, NVDA, TKO, V

**Notes:**
- CPPMF failed price fetch entirely ("no valid non-zero price found"), meaning it has $0 cost basis (see B-007)
- MRP was previously listed here but is now resolved — was caused by REI (dividend reinvestment) transactions not being counted as FIFO openings (fixed 2026-02-13)

**File:** `core/realized_performance_analysis.py` — `_build_seed_open_lots()`, `build_position_timeline()`

---

## B-003: Reconciliation gap between NAV-basis and lot-basis P&L

**Severity:** MEDIUM (downgraded from HIGH)
**Status:** Improved — gap narrowed from -$120k (39%) to -$5.2k (2.8%) after B-001/B-002/B-009/B-010/B-011 fixes
**Impact:** Official NAV P&L and lot-based P&L still diverge, but gap is now small

**Description:**
The dual-track P&L shows (updated 2026-02-14):
- `official_pnl_usd`: +$13,316 (NAV end − NAV start − net flows)
- `lot_pnl_usd`: +$18,599 (realized + unrealized + income from FIFO lots)
- `reconciliation_gap_usd`: -$5,282 (2.8% of NAV)

Previous values (2026-02-13, pre-seed-fix):
- `official_pnl_usd`: $86,360
- `lot_pnl_usd`: $206,914
- `reconciliation_gap_usd`: -$120,554 (39% of NAV)

Remaining gap likely driven by unpriceable symbols valued at $0 (B-005), AT.L seed price error (B-013), and residual synthetic position imprecision.

**Expected behavior:** Gap should continue narrowing as B-013 and B-004 are addressed. Target: < 2% of NAV.

---

## B-004: 18-34 incomplete trades (sells without matching buys)

**Severity:** MEDIUM
**Status:** Open — partially addressed by IBKR symbol normalization (Step 1)
**Impact:** Realized P&L is incomplete; some closed trades have no cost basis

**Description:**
The FIFO matcher identifies 18 exit transactions that have no matching entry. Some were caused by IBKR symbol mismatches (e.g., `AT.` vs `AT.L`) — fixed by Step 1 normalization. Remaining incomplete trades need manual backfill via `user_data/incomplete_trades_backfill.json`.

**Latest evidence (2026-02-13, `infer_shorts=False` diagnostic):**
- Incomplete trades: `34` (`33` LONG, `1` SHORT)
- Gross incomplete exit notional: `~$124,061.65`
- Source mix by notional:
  - `ibkr_flex`: `~$100,264.59`
  - `snaptrade`: `~$23,797.05`
- Top incomplete symbols by notional:
  - `MGC`: `$30,465.00`
  - `MES`: `$28,390.00`
  - `USD.HKD`: `$20,795.51`
  - `SE`: `$9,655.36`
  - `PCTY_C180_250221`: `$5,136.00`

**Next step:** Export current incomplete trades list, cross-reference with broker statements, populate backfill JSON with `manual_entry_price` and `manual_entry_date`.

**File:** `trading_analysis/fifo_matcher.py` — `export_incomplete_trades_for_backfill()`

---

## B-005: 20 unpriceable symbols valued at $0

**Severity:** MEDIUM
**Status:** Open (reduced from 22 to 20 after B-015 IBKR port fix — MGC and ZF now priced via IBKR Gateway)
**Impact:** NAV understated; any position in these symbols is invisible to returns

**Description:**
FMP cannot price these symbols, so they are valued at $0 in monthly NAV:

- **FX pairs:** GBP.HKD, USD.HKD
- **Options (custom format):** IT.X2024C320000, MSCI.X2024C340000, NMM_C70_260116, NMM_C85_260116, NXT_C30_250815, PCTY_C180_250221, PDD_C110_250815, PDD_C110_260116, PDD_C185_250815, PDD_P110_260116, PDD_P60_260116, PLTR_P80_250417, PLTR_P90_250417, SLV_C30_250620, SLV_C35_250620
- **Fixed income:** US Treasury Bill - 5.35% 08/08/2024, US Treasury Note - 4.25% 15/10/2025
- **Other:** Unknown_C2_230406

**Previously unpriceable, now fixed:**
- **MGC** (Micro Gold futures) — now priced via IBKR Gateway fallback (44 monthly bars)
- **ZF** (5-Year T-Note futures) — now priced via IBKR Gateway fallback (31 monthly bars)

**Notes:**
- Most of these are options that have likely expired or been closed — impact may be small
- FX pairs (GBP.HKD, USD.HKD) are likely IBKR cash conversion artifacts, not real positions
- Treasury instruments need a different pricing source (not FMP equity endpoint)

---

## B-006: Data coverage at 75% (target: 95%)

**Severity:** MEDIUM
**Status:** Improved — back-solved cost basis (B-002 fix) and eliminated false shorts (B-009-011 fixes) improve effective coverage
**Impact:** Confidence gating fails; `high_confidence_realized = false`

**Description:**
Transaction coverage is 75% across providers (SnapTrade: 140, Plaid: 64, IBKR Flex: 98 transactions). The 25% gap comes from:
- Positions with no transaction history at all (B-002)
- Incomplete trades missing entry side (B-004)
- Possible provider-specific gaps (accounts not linked, history windows too short)

**Source breakdown (updated 2026-02-13 post-REI fix — SnapTrade count includes REI-as-BUY):**
| Provider | Transactions |
|----------|-------------|
| SnapTrade | 140 |
| Plaid | 64 |
| IBKR Flex | 98 |

---

## B-007: CPPMF synthetic cash event skipped — no inception price available

**Severity:** LOW
**Status:** Fixed (2026-02-15)
**Impact:** Minor NAV distortion for affected months ($0.73 position)

**Resolution:** Implemented two safeguards in `core/realized_performance_analysis.py`:
1. Added synthetic price hints for synthetic current-position entries when derivable from broker USD cost/value:
   - `_synthetic_price_hint_from_position()` (lines ~248-274)
   - Used in `build_position_timeline()` when creating `synthetic_current_position` entries (lines ~587-607)
2. Made synthetic cash-event creation robust when inception price is unavailable:
   - `_create_synthetic_cash_events()` now falls back to `price_hint` if backward price lookup fails (lines ~693-700)
   - Added low-notional exclusion for synthetic current positions (`estimated_current_value_usd <= threshold`) to suppress noise such as CPPMF-sized positions (lines ~701-711)
   - Threshold wired from `DATA_QUALITY_THRESHOLDS["synthetic_cash_min_notional_usd"]` with default `$1.00` in `analyze_realized_performance()` (lines ~1660-1667)

**Description:**
CPPMF has no valid FMP price at the inception date, so the synthetic cash event (simulating capital deployment) was skipped:
- `CPPMF (LONG) on 2022-08-18: no valid non-zero price found`

This means the capital for CPPMF is unaccounted for in the cash flow reconstruction. Practical impact is negligible ($0.73 current value).

**Note:** MRP was previously affected but is now resolved — was caused by REI transactions not generating FIFO openings (fixed 2026-02-13). After the REI fix, MRP is no longer synthetic and doesn't need a synthetic cash event.

**Root cause:** CPPMF is an illiquid OTC micro-cap (Capstone Infrastructure) with no FMP price history. It likely needs a manual price backfill or exclusion.

**Proposed fix:** Either add CPPMF to a manual price override file, or exclude sub-$1 positions from synthetic cash event generation to avoid noise.

---

## B-008: AT.L first transaction is a SELL (missing earlier buys)

**Severity:** LOW
**Status:** Fixed (2026-02-15) — auto-detection and flagging
**Impact:** AT.L incomplete trade; cost basis unknown for initial position

**Resolution:** Added explicit first-exit detection and surfaced it in realized diagnostics:
- New detector `_detect_first_exit_without_opening()` identifies `(symbol, currency, direction)` buckets where the first observed day contains an exit (`SELL`/`COVER`) but no opening (`BUY`/`SHORT`) (lines ~277-348 in `core/realized_performance_analysis.py`)
- `analyze_realized_performance()` now:
  - Emits a warning summary when such symbols are detected (lines ~1510-1515)
  - Adds a `FIRST_TRANSACTION_EXIT` data-quality flag with per-symbol details (lines ~1635-1643)
  - Exposes `first_transaction_exit_count` and `first_transaction_exit_details` in realized metadata (lines ~2121-2122)

This does not auto-backfill missing buys; it makes these cases explicit so they can be prioritized for manual backfill.

**Description:**
AT.L transaction history starts with a SELL on 2025-02-24 (135 shares @ £5.33), then a BUY on 2025-09-18 (40 shares), then a SELL, then another BUY. The initial purchase that established the 135-share position is missing from all providers.

This is likely because the position was bought through IBKR before the Flex query window, or transferred in.

**Next step:** Check IBKR statements for AT.L purchase history; add to backfill JSON if found.

---

## B-009: False inferred shorts when initial buys are missing (SE/UPST case)

**Severity:** HIGH
**Status:** Fixed (2026-02-13)
**Impact:** Converts likely long exits into open short lots, materially distorting unrealized P&L and return diagnostics

**Resolution:** Replaced the fragile `not_shorts.txt` ID-based exclusion system with data-driven delta-gap short inference. `analyze_realized_performance()` now pre-computes `visible_delta` per symbol from transactions and compares against current holdings. Symbols where `holdings - delta > 0.01` (i.e., missing buy history) are added to `no_infer_symbols` set, which the FIFO matcher uses to suppress short inference. `config/not_shorts.txt` has been deleted.

Additionally, `_build_source_aligned_holdings()` was implemented to correctly compute delta-gap for source-filtered runs (e.g., `source="snaptrade"`), ensuring short inference uses provider-specific position data when attributable.

**Original evidence (2026-02-13):**
- SE and UPST were falsely inferred as open shorts (200 shares each)
- After fix: 0 inferred shorts in live diagnostic

**Files:**
- `core/realized_performance_analysis.py` — delta-gap logic in `analyze_realized_performance()` lines ~1345-1365
- `trading_analysis/fifo_matcher.py` — `no_infer_symbols` parameter in `FIFOMatcher.__init__()`

---

## B-010: Long-only portfolios can get phantom short exposure that collapses unrealized P&L

**Severity:** HIGH
**Status:** Fixed (2026-02-13)
**Impact:** Unrealized P&L can be overstated on the downside by ~$20k+ from inferred shorts that are not real portfolio exposure

**Resolution:** Fixed by the delta-gap short inference system (same fix as B-009). The FIFO matcher now receives a `no_infer_symbols` set computed from `visible_delta` vs current holdings. For long-only portfolios, sells without matching buys are correctly classified as incomplete trades rather than inferred shorts. Live diagnostic confirms 0 inferred shorts post-fix.

**Original evidence (`hc@henrychien.com`, 2026-02-13):**

With old inference:
- Inferred shorts: `15`
- Unrealized P&L: `-$24,417.34`

After delta-gap fix:
- Inferred shorts: `0`
- Unrealized P&L distortion from false shorts eliminated

**File:**
- `core/realized_performance_analysis.py` (matcher initialization in `analyze_realized_performance`)

---

## B-011: Broad `not_shorts` ID drift (not limited to SE/UPST)

**Severity:** HIGH
**Status:** Fixed (2026-02-13)
**Impact:** Curated short-inference exclusions silently fail, reopening many historical long exits as inferred shorts

**Resolution:** The entire `config/not_shorts.txt` file and transaction-ID-based exclusion system has been deleted and replaced with data-driven delta-gap analysis. The `_should_infer_short()` method in `FIFOMatcher` now uses the `no_infer_symbols` set (computed per-run from transaction deltas vs holdings) instead of brittle provider transaction IDs. This eliminates the ID drift problem entirely.

**Original evidence (2026-02-13):**
- 15 inferred short symbols, 0 current short symbols
- 18 SnapTrade sell IDs missing from `not_shorts`
- After fix: 0 inferred shorts, `config/not_shorts.txt` deleted

**Files:**
- `trading_analysis/fifo_matcher.py` — `no_infer_symbols` in `_should_infer_short()`
- `core/realized_performance_analysis.py` — delta-gap computation

---

## B-012: Official NAV-basis P&L is highly sensitive to synthetic reconstruction policy

**Severity:** HIGH
**Status:** Fixed (2026-02-15)
**Impact:** Reconciliation gap can flip sign and move by >$30k depending on synthetic-opening assumptions

**Resolution:** Implemented dual-track official P&L and synthetic-sensitivity gating in `core/realized_performance_analysis.py`:
1. Added observed-only NAV-flow path (no synthetic opening injections):
   - Builds observed-only timeline/cash/nav/flows from raw observed transactions (lines ~1695-1715)
   - Computes `official_pnl_observed_only_usd` alongside synthetic-enhanced official P&L (lines ~1987-1993)
2. Exposed both tracks and synthetic impact in API metadata:
   - `official_pnl_synthetic_enhanced_usd`
   - `official_pnl_observed_only_usd`
   - `official_pnl_synthetic_impact_usd`
   (lines ~2089-2093; also promoted in top-level response lines ~2179+)
   - Added observed-only NAV/flow series to `_postfilter` for diagnostics (lines ~2142-2153)
3. Added high-severity synthetic sensitivity flag and confidence gating:
   - `SYNTHETIC_PNL_SENSITIVITY` flag fires when absolute synthetic impact exceeds `DATA_QUALITY_THRESHOLDS["realized_synthetic_pnl_sensitivity_usd"]` (default `$5,000`) (lines ~2016-2034)
   - High-confidence gate now fails when this flag is present (lines ~2045-2079)

**Description:**
After removing inferred shorts, residual reconciliation is still unstable because official NAV-flow P&L depends heavily on synthetic opening choices (`synthetic_current_position` and `synthetic_incomplete_trade`). Runtime sensitivity diagnostics show large swings in `official_pnl_usd` while lot-based P&L stays constant.

**Evidence (`hc@henrychien.com`, `infer_shorts=False`):**
- Baseline:
  - `official_pnl_usd`: `$15,795.20`
  - `lot_pnl_usd`: `$10,030.56`
  - `reconciliation_gap_usd`: `+$5,764.64`
- Remove synthetic-current openings only:
  - `official_pnl_usd`: `$1,510.10` (delta `-$14,285.10`)
  - `reconciliation_gap_usd`: `-$8,520.46`
- Remove synthetic-incomplete openings only:
  - `official_pnl_usd`: `$32,178.85` (delta `+$16,383.65`)
  - `reconciliation_gap_usd`: `+$22,148.29`
- Remove both synthetic-current and synthetic-incomplete:
  - `official_pnl_usd`: `$18,276.03`
  - `reconciliation_gap_usd`: `+$8,245.46`

**Conclusion:** Official NAV-basis P&L is currently not robust to reasonable synthetic reconstruction variants; it is a net of large opposing synthetic effects.

**Suggested fix direction:**
1. Separate and expose an observed-only diagnostic path (no synthetic opening injections) alongside synthetic-enhanced official metrics.
2. Gate or down-rank official P&L confidence when high-notional synthetic incomplete entries are present.
3. Prioritize backfill for largest incomplete notional symbols before treating reconciliation as actionable.

**Files:**
- `core/realized_performance_analysis.py` (`build_position_timeline`, `_create_synthetic_cash_events`, `derive_cash_and_external_flows`)

---

## B-013: AT.L seed lot back-solved price is £0.01 (should be ~£4-5)

**Severity:** HIGH
**Status:** Fixed (2026-02-15)
**Impact:** AT.L unrealized P&L and NAV contribution are materially wrong; 300 pre-window shares valued at near-zero cost

**Resolution:** Updated `_build_seed_open_lots()` in `core/realized_performance_analysis.py` to seed only uncovered current shares:
- Replaced delta-based seed quantity (`shares + sells - buys`) with open-lot gap policy:
  - `pre_window_shares_by_gap = max(0, current_shares - observed_open_lot_shares)` (lines ~437-441)
  - Seed only when this gap is positive (line ~443)
- Added explicit skip warning for sell-then-rebuy patterns where delta implies pre-window shares but observed open lots already cover current holdings (lines ~444-449)
- Seed price now uses uncovered-share denominator:
  - `seed_price = (broker_cost - observed_cost) / pre_window_shares_by_gap` (line ~461)

This prevents double-counting pre-window shares that were already closed and replaced within the observed window (AT.L pattern).

**Description:**
`_build_seed_open_lots()` computes a near-zero seed price for AT.L because the pre-window cost calculation is wrong. The root cause is a sequence-of-events mismatch:

- AT.L has 400 current shares, 400 in-window buys (300 on 2026-01-30 + 100 on 2026-02-06), and 300 in-window sells (2025-02-24)
- `pre_window_shares = 400 + 300 - 400 = 300` — correct, 300 shares were held before the transaction window
- But the pass-1 observed open lots cover **all 400 current shares** (the new buys), so `obs_cost_usd ≈ $2,218.65`
- `broker_cost = $2,224.60` (total cost for all 400 shares, in USD)
- `pre_window_cost = $2,224.60 - $2,218.65 = $5.95` for 300 shares → $0.02/share → £0.01/share

**Root cause:** The back-solved formula `seed_price = (broker_cost - obs_cost) / pre_window_shares` assumes that observed open lots represent only in-window accumulation, but pass-1 open lots include the full current position (300 new buys that replaced the 300 old shares + 100 additional). The broker `cost_basis` also covers all 400 shares, so subtracting the full observed cost leaves almost nothing for the 300 pre-window shares.

**The fundamental issue:** For positions that were sold and re-bought within the transaction window (AT.L: sold 300, then bought 300+100), the pre-window shares were already closed. The broker cost basis reflects the *current* 400 shares, not the original 300. Seeding 300 pre-window shares double-counts them — the 300 sold shares should be incomplete trades, not pre-window holdings needing a seed lot.

**Affected positions:** AT.L (and any position with sell-before-rebuy patterns where the first transaction is a SELL)

**Proposed fix:** Skip seeding when all current open lots are fully explained by in-window buys. The seed should only cover the gap `max(0, current_shares - obs_open_lot_shares)`, not the `pre_window_shares` calculated from buy/sell deltas.

**File:** `core/realized_performance_analysis.py` — `_build_seed_open_lots()`, lines ~334-350

---

## B-014: Modified Dietz total return (-42%) contradicts positive official NAV P&L (+$13k)

**Severity:** HIGH
**Status:** Improved (2026-02-17) — headline return metrics now use observed-only NAV when synthetic sensitivity is high
**Impact:** Headline return metric is deeply negative despite the portfolio making money on a NAV basis

**Resolution:** Added extreme-month filtering instrumentation plus synthetic-sensitivity diagnostics in `core/realized_performance_analysis.py`:
1. Extreme-month handling enhancements:
   - Added configurable absolute return threshold `DATA_QUALITY_THRESHOLDS["realized_extreme_monthly_return_abs"]` (default `3.0`, i.e., 300%) (lines ~1822-1825)
   - Under low-confidence conditions (low coverage / synthetic openings / unpriceable symbols), returns above threshold are excluded from chain-linking and logged (lines ~1847-1854)
   - Added `EXTREME_MONTHLY_RETURNS_EXCLUDED` data-quality flag plus per-month telemetry (`extreme_return_months`) (lines ~1887-1895, ~2123)
2. B-012 dual-track + sensitivity flag (same deployment) now explains the contradiction directly:
   - `official_pnl_observed_only_usd` vs `official_pnl_synthetic_enhanced_usd`
   - `SYNTHETIC_PNL_SENSITIVITY` flag when synthetic policy impact is large (lines ~2016-2034)
3. Headline return basis safety switch (2026-02-17):
   - When `SYNTHETIC_PNL_SENSITIVITY` is high, return metrics are computed from the observed-only NAV path.
   - This prevents synthetic-enhanced reconstruction noise from driving the headline total-return/CAGR fields.

**Live-data note (2026-02-15):**
- The 300% extreme-month filter did **not** fire on live data because worst month was `+58.8%`, not >300%.
- Early-period months (Sep 2022 – Mar 2023) were roughly `-17%` to `-24%`; these compound badly without single-month >300% outliers.
- The dominant issue is questionable early synthetic NAV construction, not >300% spikes.
- `SYNTHETIC_PNL_SENSITIVITY` fired with synthetic impact `+$46.7k`.
- Dual-track official P&L showed:
  - observed-only: about `-$33k` (consistent with ~`-43%` chain-linked return)
  - synthetic-enhanced: about `+$13k`

**Open investigation (2026-02-15) — headline return uses synthetic-enhanced NAV:**
- The chain-linked % return currently uses `monthly_nav` (synthetic-enhanced), NOT observed-only NAV.
- Synthetic positions inject fabricated opening entries into `position_timeline`, and synthetic cash events (pseudo-BUYs) are added to `transactions_for_cash` — both flow into `compute_monthly_nav()`.
- This means the headline return % is built on a NAV that includes synthetic position values and synthetic cash impacts, which distorts early-period months where synthetic valuations are least reliable.
- The extreme-month filter (300% threshold) is really just a data quality guard — it doesn't fix this root cause.
- **Next step:** Evaluate whether the headline return should use observed-only NAV instead, or present both observed and synthetic-enhanced returns. Need to assess trade-offs (observed-only NAV may have gaps for positions with no transaction history at all).

**Description:**
`get_performance(mode="realized")` reports:
- `total_return`: -41.95%
- `official_pnl_usd`: +$13,316
- `lot_pnl_usd`: +$18,599
- `volatility`: 80.76%
- `max_drawdown`: -73.18%

A positive P&L with a -42% return is contradictory. The chain-linked Modified Dietz monthly returns are being distorted by extreme monthly returns in the early period, likely caused by:

1. Synthetic positions entering the NAV with incorrect valuations (B-013 AT.L at £0.01, B-002 zero-history positions)
2. Large monthly NAV swings when synthetic positions are added/valued at wrong prices
3. The math of chain-linking: a -73% drawdown month requires +270% recovery to break even, which the chain never recovers from even if absolute P&L is positive

**Evidence (2026-02-14):**
- CAGR: -14.72% over 3.42 years
- Win rate: 53.7% (more up months than down)
- Yet cumulative chain-linked return is -42%
- This pattern (positive P&L, negative chain return) only happens when there are extreme outlier months in the return series

**Expected behavior:** Total return direction should match official NAV P&L direction. If official P&L is +$13k on a ~$190k portfolio, total return should be roughly +7%, not -42%.

**Proposed fix:**
1. Fix B-013 (AT.L seed price) — removes one source of early-period NAV distortion
2. Investigate which specific months have extreme returns and trace to synthetic position valuations
3. Consider clamping or excluding months with >100% absolute returns when data coverage < 95%
4. The existing extreme-return clamp (lines 1635-1644) only fires for long-only portfolios with <100% coverage, and only clamps below -100% — may need to also clamp extreme positive returns

**File:** `core/realized_performance_analysis.py` — `compute_monthly_returns()`, chain-linking logic, and return clamping at lines ~1635-1644

---

## B-015: IBKR Gateway port mismatch — code defaults to 4001 but .env says 7496

**Severity:** MEDIUM
**Status:** Fixed (2026-02-14)
**Impact:** IBKR Gateway historical data fallback always fails with `ConnectionRefusedError('127.0.0.1', 4001)`, preventing futures pricing (MGC, ZF, MES) via IBKR

**Resolution:** Changed the default port in `settings.py` from `4001` to `7496` (TWS live port). The env var `IBKR_GATEWAY_PORT` still overrides if set. Note: `load_dotenv()` was briefly added but reverted because it loaded stale SnapTrade credentials from `.env`, breaking SnapTrade auth (401 "Invalid timestamp"). The simpler default change avoids that side effect.

**Description:**
`settings.py:638` sets `IBKR_GATEWAY_PORT = int(os.getenv("IBKR_GATEWAY_PORT", "4001"))` with a default of 4001 (IBKR live trading port). However, `.env:79` sets `IBKR_GATEWAY_PORT=7496` (TWS live port). The `.env` file is never loaded via `load_dotenv()` — `settings.py` uses raw `os.getenv()` calls, so the `.env` value is ignored unless explicitly sourced in the shell.

**Port mapping:**
| Port | Purpose |
|------|---------|
| 4001 | IB Gateway live (code default) |
| 4002 | IB Gateway paper |
| 7496 | TWS live (.env value) |
| 7497 | TWS paper |

**Evidence (2026-02-14):**
```
API connection failed: ConnectionRefusedError(61, "Connect call failed ('127.0.0.1', 4001)")
Make sure API port on TWS/IBG is open
```

This fires during the futures pricing IBKR fallback path in `analyze_realized_performance()` (lines 1441-1459) when FMP can't price MGC/ZF/MES. If TWS is running on 7496, the connection to 4001 always fails.

**Proposed fix:**
Either:
1. Add `load_dotenv()` to `settings.py` so `.env` values are loaded (standard Python practice)
2. Or change the default to match the actual TWS port: `os.getenv("IBKR_GATEWAY_PORT", "7496")`
3. Or auto-detect: try the configured port, then fall back to the other common ports (7496, 4001, 4002, 7497)

**Files:**
- `settings.py` — line 638, IBKR_GATEWAY_PORT default
- `.env` — line 79, IBKR_GATEWAY_PORT=7496
- `services/ibkr_historical_data.py` — line 93, uses `IBKR_GATEWAY_PORT` for connection

---

## Diagnostic Tool

Run `tests/diagnostics/diagnose_realized.py` to dump the full pipeline state in one shot:

```bash
python3 tests/diagnostics/diagnose_realized.py                # all sources
python3 tests/diagnostics/diagnose_realized.py --source snaptrade
python3 tests/diagnostics/diagnose_realized.py --source ibkr_flex
```

Outputs: overview metrics, synthetic positions (fully vs partial), inferred shorts (flagged as likely false when not in current holdings), incomplete trades, open lots summary, and per-ticker position coverage.

---

## B-016: Realized performance path uses untyped dicts — no formal result object

**Severity:** MEDIUM
**Status:** Fixed (2026-02-15)
**Impact:** Fragile API contract; field renames require grep-and-replace across all consumers; no IDE autocomplete or type checking

**Resolution:** Implemented `RealizedPerformanceResult` dataclass in `core/result_objects.py` with nested `RealizedMetadata`, `RealizedIncomeMetrics`, and `RealizedPnlBasis` types. The realized path now mirrors the hypothetical `PerformanceResult` pattern:
- `from_analysis_dict()` factory wraps the raw dict from `analyze_realized_performance()`
- `to_dict()` serializes back for backward compat
- `to_api_response()` centralizes API output formatting (moved from MCP layer)
- `to_summary()` provides compact summary format
- Presentation helpers (`_categorize_performance`, `_generate_key_insights`) moved into result object
- `mcp_tools/performance.py` simplified to pure wrapper (-188 lines)
- Error path unchanged (plain dict with `status: "error"`)
- All consumers updated: `mcp_tools/performance.py`, `services/portfolio_service.py`, `run_risk.py`
- 82 targeted tests pass, live MCP verified across all 3 formats (summary, full, report)

**Plan:** `docs/planning/completed/REALIZED_RESULT_OBJECT_PLAN.md`

**Files:**
- `core/result_objects.py` — `RealizedPerformanceResult`, `RealizedMetadata`, `RealizedIncomeMetrics`, `RealizedPnlBasis`
- `core/realized_performance_analysis.py` — return wrapped in typed object
- `mcp_tools/performance.py` — uses `to_api_response()`/`to_summary()`, deleted inline helpers
- `services/portfolio_service.py` — updated return type annotation
- `run_risk.py` — updated error check and report formatting

---

## Diagnostic Tool

Run `tests/diagnostics/diagnose_realized.py` to dump the full pipeline state in one shot:

```bash
python3 tests/diagnostics/diagnose_realized.py                # all sources
python3 tests/diagnostics/diagnose_realized.py --source snaptrade
python3 tests/diagnostics/diagnose_realized.py --source ibkr_flex
```

Outputs: overview metrics, synthetic positions (fully vs partial), inferred shorts (flagged as likely false when not in current holdings), incomplete trades, open lots summary, and per-ticker position coverage.

---

## Investigation Notes

### What's been fixed (Steps 1-6, previous sessions)
- IBKR symbol normalization (`AT.` → `AT.L`) — Step 1
- Month-1 Modified Dietz formula (was using `flow_weighted` instead of `flow_net`) — Step 3
- Dual-track P&L fields added — Step 4
- FX normalization for realized P&L — Step 5
- Confidence gating and acceptance checks — Step 6
- Backfill pipeline wired in (but backfill JSON still empty) — Step 2

### What's been fixed (realized-pnl-accuracy-fix plan, 2026-02-13)
- Per-symbol inception dates for synthetic positions (B-001) — Fix 1
- Two-pass FIFO with back-solved cost basis from broker data (B-002) — Fix 2
- Delta-gap short inference replacing `not_shorts.txt` (B-009/B-010/B-011) — Fix 3
- FX cache passed to seed builder for non-USD positions — Codex P1 fix
- Source-aligned holdings for delta-gap in filtered runs — Codex P1 fix

### What's been fixed (Codex bug investigation, 2026-02-15)
- B-007: Synthetic price hints + low-notional skip for CPPMF-like positions
- B-008: `_detect_first_exit_without_opening()` flags 25 symbols with truncated history
- B-012: Dual-track NAV P&L (observed-only vs synthetic-enhanced) with sensitivity gating
- B-013: Seed lot uses open-lot gap instead of delta formula — fixes AT.L £0.01 bug
- B-014: Extreme month filter infrastructure + `SYNTHETIC_PNL_SENSITIVITY` flag (300% threshold didn't fire on live data; real issue is early-period synthetic NAV quality)

### Naming cleanup (2026-02-15)
- Renamed `official_pnl_usd` → `nav_pnl_usd` across all Python source and tests
- Renamed `official_metrics_estimated` → `nav_metrics_estimated`
- Renamed `pnl_basis.official` → `pnl_basis.nav`
- All string messages updated ("Official P&L" → "NAV P&L")
- 74 tests passing after rename

### Current live results (2026-02-15, post Codex fixes + rename)
- Total return: -43.01% — **still distorted by early-period synthetic NAV (see B-014)**
- CAGR: -15.17%
- NAV P&L (synthetic-enhanced): +$13,316
- NAV P&L (observed-only): -$33,395
- Synthetic impact: +$46,711
- Lot-based P&L: +$13,322
- Reconciliation gap: -$5.58 / ~0% — **essentially zero (was -$120k / 39%)**
- Unrealized P&L: +$1,147
- Realized P&L: +$1,129
- Income: +$11,046
- Data coverage: 75%
- Unpriceable symbols: 20
- Incomplete trades: 34
- Synthetic positions: 11 current, 41 synthetic cash events
- `high_confidence_realized`: false
- Monthly returns: 2024+ chain-linked = +10.2%, 2025+ = +0.8% (reasonable)
- Early period (Sep 2022 – Mar 2023): -17% to +59% monthly swings from synthetic NAV

### Previous live results (2026-02-14, post seed-fix, pre Codex fixes)
- Total return: -41.95% (was 75.29% pre-seed-fix, 90.5% before all fixes)
- CAGR: -14.72%
- NAV P&L: +$13,316 (was +$86,360 pre-seed-fix)
- Lot-based P&L: +$18,599 (was +$206,914 pre-seed-fix)
- Reconciliation gap: -$5,282 / 2.8% (was -$120,554 / 39% pre-seed-fix) — **96% improvement**
- Unrealized P&L: +$1,143 (was +$194,267 pre-seed-fix)
- Realized P&L: +$6,409
- Income: +$11,046
- Data coverage: 75%
- Unpriceable symbols: 20 (down from 22 after B-015 fix — MGC, ZF now priced via IBKR)
- Incomplete trades: 30
- Synthetic positions: 11 current, 40 synthetic cash events
- `high_confidence_realized`: false

### Previous live results (2026-02-13)
- Total return: 75.29% (was 90.5% before fixes)
- NAV P&L: +$86,360
- Lot-based P&L: +$206,914
- Unrealized P&L: +$194,267 (inflated by B-001/B-002)
- Reconciliation gap: -$120,554
- Data coverage: 75%
- Synthetic positions: 11 current (was 14 before REI fix), incomplete trades TBD

### REI fix (2026-02-13)
- SnapTrade `REI` (dividend reinvestment) transactions now generate FIFO BUY entries alongside income events
- Fixed MRP showing as synthetic despite having a real BUY transaction (200 shares + 9.56 REI shares = 209.56 total)
- 8 symbols affected: BXMT, CBL, DSU, MRP, MSCI, SHY, SPY, STWD (56 REI activities total)
- Reduced synthetic count from 14 → 11
