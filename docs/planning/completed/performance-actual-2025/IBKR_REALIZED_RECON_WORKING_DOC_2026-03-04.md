# IBKR Realized Reconciliation Working Doc (2026-03-04)

## Primary Objective (Current)

Given IBKR transaction-history limits (roughly 365 days of prior activity), make the realized-performance engine produce an estimated return that reasonably approximates the official IBKR statement return.

This workstream is to diagnose current inference behavior using:
- IBKR statement ground truth we materialized
- engine debug inference outputs
- logical consistency checks across positions, flows, and NAV

For each major inference path, determine whether it should be:
- kept as-is
- adjusted
- removed

Decision standard: prefer inference logic that improves agreement with official IBKR return/NAV behavior while remaining mechanically consistent with observed transactions and known data limits.

### Guardrails / Constraints

- No provider-specific shaping:
  - Do not use IBKR-only (or any provider-only) hardcodes, offsets, or custom adjustments whose purpose is to force-fit estimated return to official return.
  - Any inference change must generalize across brokers/providers.

- Provider-agnostic instrument logic is allowed:
  - Instrument-standard handling is allowed when broadly valid (for example futures cash/MTM treatment, options expiration behavior), as long as it is not tied to a specific provider implementation.

- External datasets are allowed:
  - We can use provider-supplied fields (for example cost basis, holdings value) and market/FX price datasets from pricing providers.

- Synthetic reconstruction is allowed with discipline:
  - Synthetic positions/flows/inferred cash are allowed only when anchored to reasonable, defensible assumptions and evidence in observed data.
  - Preference order: observed transactions > provider-reported facts > defensible inference.

## Problem Statement

Our realized-performance engine (`get_performance(mode="realized", source="ibkr_flex")`) is materially misaligned with the official IBKR statement for the same period.

Goal: establish a repeatable reference package (ground truth + engine output + delta files) so we can iteratively fix inference logic (positions/flows/NAV reconstruction) and measure improvement.

---

## Current Official vs Engine Snapshot

Source of truth statement:
- `docs/planning/performance-actual-2025/U2471778_20250401_20260303.csv`
- Statement period: `April 1, 2025 - March 3, 2026`

Engine run used for comparison:
- `logs/performance/performance_realized_20260304_211858.json`
- Engine analysis period (snapped): `2025-04-30 -> 2026-02-28`

Key return metric:
- Official IBKR TWR: `+0.291921306%`
- Engine total return: `-8.500000000%`
- Gap: `-8.791921306 percentage points`

Key P&L deltas (USD):
- Statement NAV change: `+65.05091476099915`
- Engine NAV P&L: `+5895.8`
- NAV P&L gap: `+5830.749085239001`

- Statement realized total (all assets): `-7977.51077219`
- Engine realized P&L: `-2706.18`
- Realized gap: `+5271.33077219`

- Statement unrealized total (all assets): `+6085.70277025`
- Engine unrealized P&L: `+6534.61`
- Unrealized gap: `+448.9072297499997`

Engine reliability flags:
- `high_confidence_realized=false`
- `reliable=false`
- `data_coverage_pct=50.0`
- `reliability_reason_codes=["LOW_DATA_COVERAGE","INCOMPLETE_TRADES_EXCEED_LIMIT","RECONCILIATION_GAP_EXCEED_LIMIT","NAV_METRICS_ESTIMATED"]`

---

## Files Created / Used

### Ground Truth (IBKR Statement)
- Raw statement CSV:
  - `docs/planning/performance-actual-2025/U2471778_20250401_20260303.csv`
  - `docs/planning/performance-actual-2025/U2471778_20241231_20251231.csv`

- Materialized query tables (per statement):
  - `docs/planning/performance-actual-2025/ibkr_statement_frames/U2471778_20250401_20260303/`
  - `docs/planning/performance-actual-2025/ibkr_statement_frames/U2471778_20241231_20251231/`

Each materialized folder includes:
- `statement_tables.sqlite`
- `tables/*.csv`
- `tables_catalog.csv`
- `metadata.json`
- `all_rows_raw.csv`

### Engine Outputs (Realized + Debug Inference)
- Date-window run:
  - `logs/performance/performance_realized_20260304_211731.json`

- Full run (no custom window):
  - `logs/performance/performance_realized_20260304_211858.json`

### Reconciliation / Diagnostics Outputs
- Compact comparison (windowed run):
  - `logs/performance/ibkr_statement_vs_engine_comparison_20260304.json`

- Main comparison (full run):
  - `logs/performance/ibkr_statement_vs_engine_comparison_20260304_full.json`

- Month-by-month diagnostics:
  - `logs/performance/ibkr_monthly_diagnostics_20260304.csv`

### Code / Script Changes for Visibility
- Statement materializer script:
  - `scripts/materialize_ibkr_statement.py`

- MCP/API output visibility additions:
  - `mcp_tools/performance.py` (`debug_inference` + `inference_diagnostics`)
  - `mcp_server.py` (exposed `include_series` / `debug_inference` params)
  - `tests/mcp_tools/test_performance.py` (debug-inference coverage tests)

---

## Commands (Repro)

### 1) Materialize IBKR statements into queryable tables

```bash
python3 scripts/materialize_ibkr_statement.py \
  --input docs/planning/performance-actual-2025/U2471778_20250401_20260303.csv

python3 scripts/materialize_ibkr_statement.py \
  --input docs/planning/performance-actual-2025/U2471778_20241231_20251231.csv
```

### 2) Run realized engine with inference diagnostics

```bash
python3 - <<'PY'
from mcp_tools.performance import get_performance
res = get_performance(
    mode="realized",
    source="ibkr_flex",
    format="full",
    include_series=True,
    debug_inference=True,
    output="file",
)
print(res.get("status"))
print(res.get("file_path"))
PY
```

### 3) Inspect comparison outputs

```bash
cat logs/performance/ibkr_statement_vs_engine_comparison_20260304_full.json
sed -n '1,40p' logs/performance/ibkr_monthly_diagnostics_20260304.csv
```

---

## Notable Findings

1. Time period is close but not exact:
- Statement: `2025-04-01 -> 2026-03-03`
- Engine snapped monthly period: `2025-04-30 -> 2026-02-28`

2. First in-window month is a large drawdown:
- `2025-04-30` portfolio monthly return: `-25.390652786254154%`

3. Inference is still heavy:
- `synthetic_entry_count=23`
- `synthetic_current_position_count=6`
- `first_transaction_exit_count=19`

4. Flow diagnostics show provider-authoritative mode:
- `flow_source_breakdown.provider_authoritative_applied=52`
- `inferred_flow_diagnostics.mode="provider_authoritative_only"`

5. Windowed vs non-windowed NAV P&L inconsistency was observed:
- windowed run NAV P&L: `-2967.92`
- full run NAV P&L: `+5895.8`

---

## Diagnosis Log (2026-03-04)

### Baseline Reproduced

- Reproduced baseline from fresh run:
  - `logs/performance/performance_realized_20260304_213915.json`
- Baseline metrics (same as prior):
  - Engine total return: `-8.50%`
  - Official IBKR TWR: `+0.291921306%`
  - Gap: `-8.7919 pp`

### Evidence-Backed Observations

1. End-of-period cash is materially misaligned
- Engine month-end NAV (2026-02-28): `31941.44`
- Current non-cash holdings snapshot (same account): `31111.45`
- Engine implied end cash (`NAV - non-cash`): `+829.99`
- Official IBKR end cash (`net_asset_value__all`, Cash row): `-8727.25`
- Cash gap: `+9557.24`

Interpretation:
- Cash replay baseline/offset is likely wrong under truncated history.
- This appears to inflate NAV level and reconciliation metrics.

2. Synthetic dependence remains high
- `synthetic_entry_count=23`
- `synthetic_incomplete_trade_count=17`
- `synthetic_current_position_count=6`
- `first_transaction_exit_count=19`

Interpretation:
- Return output is heavily sensitive to synthetic reconstruction assumptions.

### What We Learned (Summary)

- The primary distortion appears to be NAV/cash-path reconstruction, not a small return-formula issue.
- End-state cash mismatch is large and concrete:
  - Engine implied end cash: `+829.99`
  - Official IBKR end cash: `-8727.25`
  - Gap: `+9557.24`
- The first in-window month is currently the dominant drag in our compounded result:
  - April 2025 monthly return: `-25.39%`
  - Compounded return excluding first in-window month is materially different (directionally positive), indicating early-window reconstruction dominates the total outcome.
- Provider-flow mode is currently authoritative (`provider_authoritative_only`), and targeted flow-shaping experiments did not resolve the return gap.
- Incomplete-trade synthetic timing changes were either neutral or harmful in this dataset; this is not the highest-leverage next fix.

### Controlled Inference Experiments (and outcomes)

1. Experiment A (reverted): anchor all `synthetic_incomplete_trade` entries near exit (`sell_date - 1s`) instead of global inception.
- Test run: `logs/performance/performance_realized_20260304_214058.json`
- Outcome:
  - Engine return moved from `-8.50%` to `-21.38%` (worse).
  - Gap vs official widened materially.
  - Added multiple synthetic TWR flow events inside April; April return became more negative.
- Decision: reverted.

2. Experiment B (reverted): horizon-based incomplete-trade backdating (only near-inception exits backdated to inception).
- Test run: `logs/performance/performance_realized_20260304_215347.json`
- Outcome:
  - No material change vs baseline.
- Decision: reverted.

3. Experiment C (reverted): force futures exclusion from NAV valuation when MTM events unavailable.
- Test run: `logs/performance/performance_realized_20260304_215145.json`
- Outcome:
  - No material change vs baseline in this IBKR run.
- Decision: reverted.

### Current Diagnosis Priority

Highest-priority hypothesis to test next:
- Add a provider-agnostic cash baseline anchor (using observed current cash balances) and make cash reconstruction explicit in diagnostics.

Rationale:
- Largest concrete, measured structural mismatch is end cash (`+829.99` implied vs `-8727.25` official).
- This is a core NAV/return plumbing issue that likely affects all providers when history is truncated.

---

## Realized Return Inference Logic Reference (Engine)

This section captures the key inferred values/decisions that can move realized return output when history is incomplete.

### MCP entry points and visibility

- MCP tool wiring:
  - `mcp_server.py:528` (`get_performance` exposes `include_series` + `debug_inference`)
  - `mcp_tools/performance.py:325` (`get_performance` orchestrator)
  - `mcp_tools/performance.py:192` (`_build_inference_diagnostics`)
- Core realized engine entry:
  - `core/realized_performance_analysis.py` (invoked via service in `mcp_tools/performance.py:59`)

### Inference stack (in execution order)

1. Holdings scope attribution inference
- `core/realized_performance_analysis.py:734` (`_build_source_scoped_holdings`)
- `core/realized_performance_analysis.py:536` (`_build_current_positions`)
- Logic:
  - If `source="all"`: consolidated holdings scope.
  - Else: source-scoped holdings, with ambiguous cross-source symbols excluded.
  - This directly changes which current positions are treated as in-scope anchors.

2. Missing-history detection inference
- `core/realized_performance_analysis.py:995` (`_detect_first_exit_without_opening`)
- Logic:
  - Flags symbols whose first observed trade is an exit (`SELL`/`COVER`) with no opening on that first date.
  - Signals truncated history and feeds data-quality diagnostics.

3. Seeded pre-window lot inference (back-solved cost basis)
- `core/realized_performance_analysis.py:1069` (`_build_seed_open_lots`)
- Called in pipeline at `core/realized_performance_analysis.py:3634`
- Logic:
  - For LONG positions with broker cost basis, infer pre-window shares not explained by observed open lots.
  - Back-solve seed lot price: `(broker_cost - observed_lot_cost) / pre_window_shares`.
  - Seed lot timestamp is anchored at earliest symbol transaction minus 1 second.

4. Synthetic position inference (missing openings + incomplete trades)
- `core/realized_performance_analysis.py:1216` (`build_position_timeline`)
- Called at `core/realized_performance_analysis.py:3664`
- Logic:
  - Adds synthetic openings when `required_entry_qty > known_openings`.
  - Adds synthetic incomplete-trade entries for unmatched exits.
  - Date anchoring depends on `use_per_symbol_inception`:
    - `False` (IBKR-safe default): global inception anchoring.
    - `True` (complete-history safe): per-symbol earliest transaction anchoring.

5. Synthetic cash-event inference for synthetic positions
- `core/realized_performance_analysis.py:1528` (`_create_synthetic_cash_events`)
- Called at `core/realized_performance_analysis.py:3926`
- Logic:
  - Converts synthetic entries into pseudo `BUY`/`SHORT` cash events.
  - Price resolution is strict backward-only lookup, then fallback `price_hint`.
  - Invalid/low-notional events are skipped with warnings.

6. Cash replay + inferred external-flow inference
- `core/realized_performance_analysis.py:1606` (`derive_cash_and_external_flows`)
- Called repeatedly from `core/realized_performance_analysis.py:4044` onward
- Logic:
  - Replays trades + income + provider flow events + futures MTM into cash snapshots.
  - If inference is enabled and cash goes negative: infer contribution (positive external flow) to zero cash.
  - If cash later exceeds outstanding inferred contributions: infer repayment withdrawal (negative external flow).
  - Inference is disabled in provider-authoritative replay branches and can be force-disabled.
  - Futures notional is suppressed from cash replay (fees + MTM cash impacts are retained).
  - Unpriceable-symbol trade notional can be suppressed (fees retained).

7. Provider-flow authority inference + fallback partitioning
- `core/realized_performance_analysis.py:2510` (`_deduplicate_provider_flow_events`)
- `core/realized_performance_analysis.py:2580` (`_build_provider_flow_authority`)
- Applied in orchestration at `core/realized_performance_analysis.py:3508` and `:4071-4470`
- Logic:
  - Provider flow rows are deduped by transaction-id or fallback fingerprint.
  - Slice-level authority is granted when events exist, or deterministic no-flow metadata exists.
  - When slices are non-authoritative/fallback, engine partitions activity and replays fallback branches with inference.

8. NAV inference + TWR monthly return inference
- `core/realized_performance_analysis.py:1988` (`compute_monthly_nav`)
- `core/realized_performance_analysis.py:2141` (`compute_twr_monthly_returns`)
- Synthetic TWR flow adapter:
  - `core/realized_performance_analysis.py:871` (`_synthetic_events_to_flows`)
  - used at `core/realized_performance_analysis.py:4580`
- Logic:
  - NAV = valued positions + replayed cash snapshots.
  - Futures positions are excluded from NAV valuation to avoid MTM double-counting.
  - Monthly return is chained from daily GIPS-style flow-adjusted returns.
  - Synthetic positions are injected into TWR flow stream as compensating flows.

9. Synthetic-sensitivity and reliability inference (quality gates)
- `core/realized_performance_analysis.py:4733-5086`
- Logic:
  - Computes data coverage from current holdings vs observed opening keys.
  - Computes synthetic policy impact (`nav_pnl_synthetic_enhanced - observed_only_nav_pnl`).
  - Computes reconciliation gap (`nav_pnl - lot_pnl`) and reliability gates.
  - Sets `high_confidence_realized`, `reliable`, and reason codes (for example `LOW_DATA_COVERAGE`, `NAV_METRICS_ESTIMATED`).

### Why this matters for IBKR reconciliation

- Current IBKR run shows heavy synthetic dependence (`synthetic_entry_count`, first-exit flags, low coverage), so realized return mismatch is expected to be dominated by steps 3-7 above.
- The new `debug_inference` payload surfaces these intermediate artifacts so we can compare each inferred component against statement truth and narrow the largest error contributors first.

---

## Current Working Baseline (for future deltas)

Use `logs/performance/ibkr_statement_vs_engine_comparison_20260304_full.json` as the baseline until superseded.

Acceptance direction for future fixes:
- Return gap `|engine - statement|` should shrink materially from `8.7919 pp`.
- NAV P&L gap should converge toward `0`.
- Reliability gates should improve (`data_coverage`, `reconciliation_gap`, `nav_metrics_estimated`).

---

## Cash Anchor Diagnostic Pass (2026-03-04, 22:22 ET)

### Code changes applied

- `core/realized_performance_analysis.py`
  - Added observed end-cash extraction from current position rows (`ticker=CUR:*` / `type=cash`) with source/institution/account scoping.
  - Added explicit cash anchor diagnostics:
    - observed end cash (USD)
    - replayed end cash (unanchored)
    - anchor offset
    - replayed end cash (anchored)
  - Added month-end NAV decomposition outputs:
    - `monthly_nav_components` (current engine path)
    - `monthly_nav_components_cash_anchored` (diagnostic-only anchored path)
    - observed-only equivalents
  - Important behavior: anchor is **diagnostic-only** (`cash_anchor_applied_to_nav=false`) and does not change production return computation.

- `core/result_objects/realized_performance.py`
  - Added typed fields so new cash-anchor diagnostics survive result-object serialization.

- `mcp_tools/performance.py`
  - Exposed new diagnostics in `inference_diagnostics`:
    - `cash_anchor_diagnostics`
    - `monthly_nav_components`
    - `monthly_nav_components_cash_anchored`
    - observed-only equivalents.

### Runs and outcomes

- Intermediate experimental run (anchor applied directly to NAV path):
  - `logs/performance/performance_realized_20260304_222039.json`
  - Result: return worsened to `-11.24%` (gap widened), so this was not kept as active behavior.

- Final diagnostic-only run:
  - `logs/performance/performance_realized_20260304_222256.json`
  - Engine total return: `-8.50%` (unchanged from baseline)
  - Official IBKR TWR: `+0.291921306%`
  - Gap: `-8.791921306 pp` (unchanged baseline gap)

### New measured cash diagnostics (final run)

- `observed_cash_end_usd=-8728.37`
- `cash_replay_end_unanchored_usd=-234.30`
- `cash_anchor_offset_usd=-8494.08`
- `cash_replay_end_anchored_usd=-8728.37`
- `cash_anchor_applied_to_nav=false`

Month-end decomposition example (`2026-02-28`):
- Engine path (`monthly_nav_components`):
  - `nav_usd=31941.44`
  - `positions_value_usd=31554.46`
  - `cash_value_usd=+386.98`
- Diagnostic anchored path (`monthly_nav_components_cash_anchored`):
  - `nav_usd=23447.36`
  - `positions_value_usd=31554.46`
  - `cash_value_usd=-8107.10`

Interpretation:
- End-cash mismatch is now explicit and quantified in output.
- A flat cash offset can align end cash, but directly applying it to NAV path distorts return dynamics (especially early months), so it should remain a diagnostic surface until we model cash path shape more realistically.

### Follow-up Experiment Status

- The temporary non-flat cash-anchor experiment (`flow_weighted`) was reverted.
- Current engine behavior remains diagnostics-only for cash anchor (`cash_anchor_applied_to_nav=false`).

### Additional Pipeline Fix (2026-03-04, 22:41 ET)

Change:
- `compute_twr_monthly_returns` now skips pre-start external flows (flow date before first NAV date) and treats them as opening capital state instead of snapping them into inception-day denominator.

Why:
- We observed synthetic pre-inception flows being snapped onto first NAV day by business-day normalization.
- This can distort first-month TWR math in generic truncated-history scenarios.

Run:
- `logs/performance/performance_realized_20260304_224113.json`
- Return remained `-8.50%` (no headline-gap improvement in this IBKR dataset), but diagnostics now explicitly show:
  - `Skipped 23 pre-start external flow(s) (net $36,099.20); treated as opening capital.`

---

## Fundamental Issues (Root Cause Catalog)

These are the structural problems in the realized-performance engine that collectively produce the return gap. Each must be addressed for the engine to produce reliable results across providers.

### Issue 1: Margin Balance Not Modeled

**Status**: Open — highest priority

**Problem**: The engine reconstructs NAV as `positions_value + replayed_cash`, but seeds cash replay at zero. For margin accounts, actual cash is deeply negative throughout the period (IBKR account runs -$8,727 to -$11,097). The engine doesn't model margin debt, so NAV is inflated by ~$9-15k across the period.

**Impact**:
- NAV denominator is wrong for every monthly TWR calculation
- April 2025 shows -25.39% return — likely an artifact of a ~$35k phantom NAV (real NAV was ~$22k)
- Compounding from a wrong first-month return poisons the entire chain

**Evidence**:
- Engine month-end cash path (unanchored): starts +$4,194 → peaks +$7,812 → ends +$387
- Official IBKR cash path: starts -$11,097 → ends -$8,727
- Cash gap varies from +$15,291 (start) to +$9,114 (end) — NOT constant

**Provider data availability for fix**:
| Provider | Current cash balance | Historical cash | Source |
|----------|---------------------|----------------|--------|
| Plaid | Yes | No | `balances.current` minus holdings sum → `CUR:USD` position |
| Schwab | Yes | No | `currentBalances.cashBalance` or `marginBalance` → `USD:CASH` position |
| IBKR Flex | Yes (end snapshot via `CUR:*` / `type=cash` position rows) | No | Flex statement + normalized position rows |

All three already inject cash into position rows (`CUR:*` / `type=cash`), so the end-of-period observed cash is provider-agnostic (already implemented in `_compute_observed_cash_end_usd()`).

**Potential fix directions**:
1. **Back-solve start cash**: `start_cash = observed_end_cash - sum(all_transaction_cash_impacts)`. Replay forward with correct seed. Risk: truncated history means incomplete transaction sum.
2. **Start + end anchor with interpolation**: If we can get both endpoints, interpolate cash path and blend with replayed cash. But we only have end from broker data.
3. **Use observed end cash + backward replay**: Replay cash impacts backward from known end to infer each month-end cash. More accurate than flat offset but same truncation risk.
4. **Flat end-anchor offset**: Simplest, but distorts early months (demonstrated: cash error varies +$9k to +$15k across period).

**Constraint**: No provider-specific shaping. Fix must generalize.

### Issue 1 Deep-Dive Update (2026-03-05)

Implementation (diagnostic-only, no behavior change):
- Reintroduced explicit Issue 1 diagnostics in engine output:
  - observed end cash from scoped cash rows
  - replayed end cash (unanchored)
  - anchor offset
  - month-end NAV component decomposition (current + cash-anchored diagnostic views)
- `cash_anchor_applied_to_nav` remains `false` (diagnostics-only).

Run used:
- `logs/performance/performance_realized_20260305_010932.json`

Measured values:
- `observed_cash_end_usd = -8731.215520781556`
- `cash_replay_end_unanchored_usd = -234.2951983580001`
- `cash_anchor_offset_usd = -8496.920322423555`
- replay mode: `provider_authoritative_only`

Month-end decomposition example:
- `2025-03-31` (engine path): cash `+3473.88`
- `2026-02-28` (engine path): cash `+386.98`
- `2025-03-31` (diagnostic anchored): cash `-5023.04`
- `2026-02-28` (diagnostic anchored): cash `-8109.94`

Key finding:
- Flat opening-cash/end-cash anchoring is not a viable fix for return quality in this IBKR case.
- Controlled check (constant cash shift to match observed end cash) moved compounded return from about `-8.5%` to about `-35.1%` (worse).

Implication for Issue 1:
- The core problem is not only level alignment at endpoint; it is cash-path shape under truncated history.
- Next Issue 1 candidate should be a provider-agnostic path-shape model (or confidence fallback usage), not a constant baseline shift.

### Issue 2: Synthetic Position Cash Injection

**Status**: Open

**Problem**: When history is truncated and positions are synthetically reconstructed (23 synthetic entries in current run), the engine creates synthetic `BUY`/`SHORT` cash events for those positions. These inject phantom cash flows into the replay, distorting the cash path.

**Impact**:
- April cash jumps from +$4,194 to +$7,812 — the +$3,600 spike correlates with synthetic position entries being injected at window start
- Synthetic cash events can feed into external flow inference in non-authoritative/fallback replay branches; in this IBKR run (`provider_authoritative_only`), inferred external-flow adjustments are disabled

**Evidence**:
- `synthetic_entry_count=23`, `synthetic_incomplete_trade_count=17`
- `Skipped 23 pre-start external flow(s) (net $36,099.20)` in TWR diagnostics; these are synthetic-flow artifacts carried into denominator handling

**Relationship to Issue 1**: Even if we fix the cash seed (Issue 1), synthetic cash injections would still perturb the path. These are partially independent problems.

### Issue 3: First-Month Return Dominance

**Status**: Open — dependent on Issues 1 & 2

**Problem**: The first in-window month (April 2025) shows -25.39% monthly return, which dominates the compounded result. Excluding April, the chain flips strongly positive (~+22.64%), indicating April dominates path behavior.

**Impact**: A single bad month at the start of a compounding chain overwhelms 10 months of reasonable returns.

**Evidence**:
- April 2025 monthly return: -25.39%
- Excluding April compounds to ~+22.64% (far from official +0.29%), so the issue is not only sign direction but full path calibration
- This is likely an artifact of wrong NAV denominator (Issue 1) + synthetic cash spike (Issue 2)
- Real IBKR NAV at April start was ~$22k; engine had ~$35k

**Fix**: Likely resolves automatically once Issues 1 and 2 are addressed. Not a separate code fix.

### Issue 4: Cash Replay Baseline Assumption

**Status**: Open — closely related to Issue 1

**Problem**: `derive_cash_and_external_flows()` replays from an implicit zero baseline. There is no mechanism to seed the replay with an observed opening balance.

**Impact**: All downstream NAV and TWR calculations inherit the wrong cash level from day one.

**Potential fix**: Add an optional `opening_cash_balance` parameter to the cash replay function. Source it from back-solved end cash (Issue 1 option 1) or from a provider-supplied starting balance if available.

### Issue 5: No Month-End Cash Ground Truth

**Status**: Structural limitation — no fix available from current provider data

**Problem**: None of our providers (Plaid, Schwab, IBKR) supply historical month-end cash balances. We only have current (end-of-period) snapshots. This means we cannot directly validate the cash path at intermediate months.

**Impact**: We can anchor the endpoint but cannot verify whether the month-by-month cash trajectory is correct. Monthly TWR accuracy depends on correct intermediate NAV, which depends on correct intermediate cash.

**Mitigation**: If Issues 1 and 4 are fixed (correct seed + correct replay), the intermediate values should be approximately correct as long as the transaction history within the window is complete. The remaining error would come from missing pre-window transactions (Issue 2).

### Issue 6: Synthetic Cash Events Ignore Futures Instrument Type

**Status**: Partially resolved (Phase 1 implemented on 2026-03-05)

**Problem**: `_create_synthetic_cash_events()` (line 1686) has no awareness of instrument type. Every synthetic entry — equity, futures, or options — is converted to a pseudo BUY/SHORT with full `price * quantity` notional as the cash impact. For futures, this is wrong: opening a futures contract posts **margin** (typically 5-15% of notional), not the full notional value. Additionally, the pseudo transactions emitted don't carry `is_futures=True`, so even when they flow into `derive_cash_and_external_flows()`, they bypass the futures notional suppression logic (line 1975-1986) and are treated as equity trades.

**Two sub-bugs**:
1. `_create_synthetic_cash_events()` doesn't check `entry.get("instrument_type")` — treats all instruments as equities
2. Pseudo transactions emitted (line 1748-1759) don't carry `is_futures` flag, so the downstream cash replay's futures handling is never triggered

**Contrast with real transaction path**: The real cash replay in `derive_cash_and_external_flows()` correctly handles futures — it suppresses notional and only applies fees (line 1975-1986). The synthetic path entirely bypasses this.

**Impact**: Synthetic futures entries create phantom cash outflows at full notional value, inflating the cash distortion. For example, a synthetic Hang Seng futures contract at HKD ~20,000 would inject ~$2,500 USD in phantom cash movement when the real cash impact was just the margin deposit (~$200-400).

**Evidence**: The synthetic entries do carry `instrument_type` (set at line 1565 and 1600-1603), so the data is available — it's just not read by `_create_synthetic_cash_events()`.

**Implemented (Phase 1, provider-agnostic)**:
1. `_create_synthetic_cash_events()` now normalizes `instrument_type` and `is_futures` from synthetic entries.
2. Synthetic futures entries are skipped (no full-notional pseudo BUY/SHORT cash events), with explicit warning output.
3. Non-futures pseudo transactions now carry `instrument_type` and `is_futures` metadata.
4. `_synthetic_events_to_flows()` now skips futures pseudo events so full-notional synthetic futures do not distort TWR external-flow math.

**Files changed**:
- `core/realized_performance_analysis.py`
- `tests/core/test_realized_performance_analysis.py`

**Validation (main branch)**:
- `python3 -m py_compile core/realized_performance_analysis.py tests/core/test_realized_performance_analysis.py` (pass)
- `pytest -q tests/core/test_realized_performance_analysis.py -k "synthetic_cash_events or synthetic_events_to_flows"` (pass)
- `pytest -q tests/core/test_realized_performance_analysis.py -k "derive_cash_explicit_instrument_type_futures or futures_cash_replay_fee_only_excludes_notional or synthetic_cash_events_skip_futures_entries or synthetic_events_to_flows_skips_futures_events"` (pass)
- Realized run: `logs/performance/performance_realized_20260305_005823.json`
  - `total_return=-8.5` (unchanged vs baseline, expected for this IBKR sample because synthetic entries are equities, not futures)

**Remaining gap**:
- Synthetic futures P&L is still not represented in NAV without synthetic MTM/valuation modeling (Issue 7).

### Issue 7: Synthetic Futures Positions Are Invisible to NAV

**Status**: Open — confirmed structural gap

**Problem**: `compute_monthly_nav()` (line 2146) intentionally excludes futures from position valuation (line 2206-2207) because real futures P&L flows through cash via FUTURES_MTM daily settlement events. This is correct for observed futures with actual MTM events from the broker. But for **synthetic futures positions** (reconstructed to fill truncated history), neither path contributes to NAV:

1. **Position value**: Excluded by the futures skip — contributes $0
2. **MTM cash settlements**: No historical MTM events exist for pre-window synthetic positions — contributes $0

So synthetic futures are completely invisible to NAV. They have no effect on return measurement except through the (incorrect) full-notional cash injection from Issue 6.

**Why this matters**: For equities, the synthetic position model works: we value the synthetic position at `price * quantity` at each month-end, and price changes flow through NAV naturally. For futures, the equivalent would be to track the **unrealized P&L** (change in futures price × quantity × multiplier), not the notional. But neither valuation path exists for synthetic futures today.

**Example**: If we synthetically reconstruct a Hang Seng futures position that was opened before the transaction window:
- The position contributes $0 to NAV every month (excluded as futures)
- No MTM settlements exist to flow P&L through cash
- The only cash impact is the (wrong) full-notional injection from Issue 6
- Net effect: futures gains/losses during the analysis period are completely missed

**Fix direction** (two options, not mutually exclusive):

1. **Simulate synthetic MTM events**: For synthetic futures, generate pseudo MTM cash events from observed price changes: `mtm_amount = qty * (price_month_end - price_month_start) * multiplier * fx`. This mirrors what the broker does daily. Provider-agnostic — only needs price data we already have in `price_cache`.

2. **Include synthetic futures in position valuation as unrealized P&L**: Instead of skipping them in `compute_monthly_nav()`, value synthetic futures at `qty * (current_price - entry_price) * multiplier * fx`. This avoids generating fake cash events but requires tracking entry price through the timeline.

**Preference**: Option 1 (synthetic MTM) is more consistent with the existing architecture — real futures use MTM cash, so synthetic futures should too. Option 2 would create a special valuation path only for synthetic futures, which adds complexity.

**Relationship to other issues**:
- Issue 6 (synthetic cash notional): Must be fixed first or simultaneously — can't inject full notional AND add MTM, that would double-count
- Issue 1 (margin balance): Even with synthetic MTM, the cash seed still needs to be correct

### Issue 8: MTM Diagnostic Fields Missing from Serialized Output (False Alarm on Plumbing)

**Status**: Resolved — was a reporting bug, not a data flow bug

**Original hypothesis**: Futures MTM settlement events not reaching cash replay, based on `futures_mtm_event_count=None` in output.

**Actual finding**: The MTM events ARE flowing through correctly. Monkey-patch tracing confirmed:
- 101 MTM events reach `derive_cash_and_external_flows()`
- `replay_diagnostics` records `futures_mtm_event_count=101`, `futures_mtm_cash_impact_usd=-10,061.07`
- The fields appear as `None` in serialized output because `RealizedMetadata` dataclass lacks typed fields for `futures_mtm_event_count` and `futures_mtm_cash_impact_usd` — they exist in the replay diagnostics dict but get dropped during `to_dict()` serialization.

**Remaining fix**: Add `futures_mtm_event_count` and `futures_mtm_cash_impact_usd` as typed fields on `RealizedMetadata` so they appear in API/file output. Low priority — purely a reporting gap, not a computation issue.

**Key data point**: Even with $10,061 of MTM cash impact flowing through, the return is still -8.5%. This means the MTM events are not the driver of the gap — the cash seed / margin balance issue (Issue 1) is the dominant problem.

---

## Fix Priority Order

1. **Issue 1 + Issue 4** (cash seed): Back-solve starting cash from observed end cash and replay transactions. Seed the forward replay correctly. Highest-leverage structural fix. This is the margin balance problem.
2. **Issue 7** (synthetic futures invisible to NAV): Add synthetic MTM events or position valuation for synthetic futures. (Note: not active in current IBKR dataset.)
3. **Issue 2** (synthetic cash injection): Review whether synthetic position cash events should be excluded from the cash replay entirely.
4. **Issue 3** (first-month dominance): Validate after fixing 1+2. Likely resolves automatically.
5. **Issue 5** (no intermediate ground truth): Accept as structural limitation. Monitor via NAV decomposition diagnostics.
6. ~~**Issue 6**~~ (Phase 1 resolved): Synthetic futures pseudo cash notional is now suppressed; metadata propagation added; remaining futures modeling work moved to Issue 7.
7. ~~**Issue 8**~~ (resolved): MTM events were flowing through correctly. Serialization bug only — add typed fields to `RealizedMetadata`.

---

## MTM Double-Counting Fix + FX Conversion Discovery (2026-03-04, late)

### MTM Double-Counting Fix (COMPLETED)

**Plan**: `docs/planning/MTM_DOUBLE_COUNTING_FIX_PLAN.md`

**Problem**: IBKR Flex `StatementOfFundsLine` reports each futures MTM event in both native currency (e.g. HKD) and base currency (USD). The normalizer `normalize_flex_futures_mtm()` passed both through because the dedup key included `(amount, currency)`.

**Fix applied**: Two-pass dedup in `ibkr/flex.py`:
- Pass 1 (existing): exact-duplicate dedup `(account_id, date, raw_symbol, amount, currency)`
- Pass 2 (new): cross-currency collapse — groups by `(account_id, date, raw_symbol)`, for multi-currency groups keeps only `base_currency` entries

**DB cleanup**: Deleted 303 old MTM rows, re-ingested → 85 rows (all USD). HKD duplicates eliminated.

**Before/After**:
- Before: 303 MTM rows (48 MHI in HKD + 48 MHI in USD + 207 other USD)
- After: 85 MTM rows (16 MHI in USD + 69 other USD)
- MTM cash impact: was ~-$9,603 (double-counted) → now -$5,210 (correct)

**Tests**: 11 tests pass (5 existing + 6 new cross-currency dedup tests).

**Files changed**:
- `ibkr/flex.py` — `normalize_flex_futures_mtm()` two-pass dedup + `base_currency` param
- `tests/ibkr/test_flex_futures_mtm.py` — 6 new tests

### FX Conversion Trades Discovery (NEW ISSUE)

**Problem**: Currency conversion trades (e.g. `USD.HKD SELL qty=2675 px=7.77`) are classified as regular SELL trades in FIFO transactions. These are zero-sum in base currency (converting cash between currencies), but the back-solve/cash replay counts the full notional as trade proceeds.

**Impact**: Single USD.HKD conversion on 2025-04-07 adds $20,789 of phantom trade proceeds. Total FX conversion impact: $20,929 across 3 trades.

**FX conversion trades found**:
| Date | Symbol | Type | Amount |
|------|--------|------|--------|
| 2025-03-10 | USD.HKD | SELL | $6.72 |
| 2025-04-04 | GBP.HKD | SELL | $133.18 |
| 2025-04-07 | USD.HKD | SELL | $20,788.79 |

**Fix in diagnostic script**: `scripts/ibkr_cash_backsolve.py` now detects and excludes FX pair symbols (`XXX.YYY` where both parts are known currencies).

**TODO**: The realized performance engine (`derive_cash_and_external_flows()`) likely has the same issue — FX conversions flow through as regular trade cash impacts. Need to check and fix there too.

### Updated Back-Solve Results

With MTM dedup fix + FX exclusion:

| Approach | Gap vs Statement |
|----------|-----------------|
| Before all fixes | -$22,630 |
| Approach 1 (trades + income + flows + MTM) | **-$1,702** |
| Approach 2 (trades + flows + MTM) | -$1,878 |
| Approach 3 (trades + income + ext flows + MTM) | -$2,840 |

Best result: **Approach 1** back-solves starting cash to -$12,799 vs statement -$11,097 (gap -$1,702, ~15%).

The remaining $1,702 gap is likely from:
1. Pre-window trades (buys from before the Flex window without corresponding sells)
2. Minor FX P&L on currency conversions (not truly zero-sum if rates changed)
3. Possible income/fee overlap between event types

### Updated Issue 8 Note

MTM event count after dedup fix: 85 events (was 101 before). The 16 HKD duplicates for MHI were the cross-currency double-counting. The `futures_mtm_cash_impact_usd` should now be approximately halved in engine output.

---

## Income/Fee/MTM Segment + Cross-Currency Dedup Fix (2026-03-04, late)

**Plan**: `docs/planning/FLEX_INCOME_FEE_DEDUP_PLAN.md`
**Commit**: `456992fd fix: IBKR Flex segment/cross-currency dedup for income, fees, and MTM`

### Three Bugs Fixed

1. **BROKERINTPAID double-counting**: `_cash_classification()` classified `BROKERINTPAID`/`BONDINTPAID` as fee flows, while `_income_trade_type_for_cash_type()` already captured them as INTEREST income. Both pipelines emitted events for the same raw rows → double-counted interest charges in cash replay. Fix: removed from `fee_types`.

2. **Income segment dedup**: `normalize_flex_cash_income_trades()` had no dedup. IBKR reports each event once per account segment (S/C/F) AND per account variant (`U2471778` vs `-`), producing up to 6x duplication. Fix: two-pass dedup (same pattern as MTM fix).

3. **Flow segment dedup**: `normalize_flex_cash_rows()` had CashTransaction/Transfer overlap dedup but no segment dedup within CashTransaction. Fix: two-pass dedup with `raw_type` discriminator to distinguish FEES from COMMADJ from ADVISORFEES.

### Implementation Details

- Shared helpers added: `_is_synthetic_transaction_id()`, `_dedup_account_id()`, `_select_dedup_winner()`
- Account ID excluded from all dedup keys (IBKR reports `-` vs real account ID for same event)
- Segment dedup key (income): `(date, symbol, type, round(amount,8), currency)` — signed amount
- Cross-currency key (income): `(date, symbol, type)` — NO amount (same event has different magnitudes across currencies)
- Flow dedup keys include `raw_type` to prevent false collapses of distinct fee types

### Results After Fix + Re-Ingest

| Category | Before Fix | After Fix | Statement | Notes |
|----------|-----------|-----------|-----------|-------|
| Income events | 118 rows | 46 rows | — | Segment dedup + cross-currency collapse |
| Dividends | $364.82 (2x) | $306.97 (33 rows) | $182.41 | Gross; $124.56 = withholding tax (WHTAX excluded by design) |
| Interest | -$651.62 (2.5x) | -$308.58 (13 rows) | -$252.40 | Includes HKD→USD conversion delta |
| Fee events | 90 rows | 35 rows | — | BROKERINTPAID removed + segment dedup |
| Fees | -$999.70 (4.2x) | -$319.03 (35 rows) | -$237.03 | BROKERINTPAID removed from fees |
| MTM events | 101 rows | 85 rows | — | Cross-currency dedup (prior fix) |

~$966 of phantom cash drains removed from the pipeline.

### Back-Solve Impact

Gap went from **-$1,702 → -$2,695** (widened). This is expected: the double-counted fees/interest were accidentally compensating for the real MTM discrepancy. Removing phantom cash drains exposed the underlying gap.

### MTM FX Aggregation Investigation

The remaining MTM discrepancy ($-5,210 engine vs $-3,589 statement = ~$1,621 gap) was investigated. Cause: **FX aggregation mismatch** — our normalizer converts each daily MHI MTM event from HKD→USD at that day's FX rate, then sums. IBKR's Cash Report converts the aggregate HKD total at a single (likely period-end) rate. Sum of daily FX conversions ≠ conversion of the sum.

Measured: MHI aggregate HKD total = -25,300 HKD. Our daily-converted sum = -$4,852.74. Statement bulk conversion = -$3,256.47. Delta = -$1,596, which accounts for almost all of the $1,621 MTM gap.

**Conclusion**: This is inherent to multi-currency daily accounting vs period-end bulk conversion. Not a bug — it's a measurement methodology difference. The daily-converted approach is actually more accurate for performance measurement.

### Updated Back-Solve Numbers

| Metric | Value |
|--------|-------|
| Best back-solve gap | -$2,695 |
| Of which FX aggregation | ~-$1,596 |
| Residual after FX explanation | ~-$1,099 |

The ~$1,099 residual is likely from:
1. Pre-window trades (truncated history)
2. Minor FX P&L on currency conversions
3. Rounding across daily FX conversions

### Tests

17 new tests added to `tests/ibkr/test_flex.py` (65 total pass):
- 8 income dedup tests, 6 flow dedup tests, 3 `_cash_classification` tests
- Codex review: Round 1 FAIL → Round 2 FAIL → Round 3 PASS

---

## Updated Fix Priority Order (Post-Dedup)

1. **Issue 1 + Issue 4** (cash seed): Back-solve starting cash from observed end cash and replay transactions. Highest-leverage structural fix.
2. **Issue 7** (synthetic futures invisible to NAV): Add synthetic MTM events for synthetic futures.
3. **Issue 2** (synthetic cash injection): Review synthetic position cash event handling.
4. **Issue 3** (first-month dominance): Validate after fixing 1+2.
5. **Issue 5** (no intermediate ground truth): Accept as structural limitation.
6. ~~**Issue 6**~~ (resolved): Synthetic futures pseudo cash notional suppressed.
7. ~~**Issue 8**~~ (resolved): MTM events flowing correctly, serialization-only gap.

---

## Back-Solve Diagnostic Fix: Date Filtering + FX Conversion (2026-03-05)

**Plan**: `docs/planning/BACKSOLVE_FX_DATE_FILTER_PLAN.md`

### Problem

The back-solve diagnostic script (`scripts/ibkr_cash_backsolve.py`) had a
-$2,695 gap vs the IBKR statement. Full decomposition revealed the gap was
NOT in the normalizers — it was in the diagnostic script itself:

| Category | Delta | Root Cause |
|----------|-------|------------|
| Pre-period trades | +$3,879 | 16 Mar 2025 trades outside statement period |
| MTM FX aggregation | -$1,621 | Daily HKD→USD vs bulk conversion |
| GBP face-value error | +$470 | AT.L buys in GBP treated as USD |
| Withholding tax | +$125 | Gross dividends vs net (by design) |
| Fee residual | -$82 | GBP fees not converted |
| FX translation | -$54 | Statement FX gain not captured |
| Interest FX | -$47 | HKD interest daily vs bulk |
| HKD fee face-value | -$30 | Futures fees in HKD treated as USD |
| Trade rounding | +$55 | Minor |
| **TOTAL** | **+$2,695** | Matches gap exactly |

Key validation: in-period USD trade sales matched statement to the penny
($22,303.94 = $22,303.94). The normalizers are clean.

### Fixes Applied

1. **Date filtering**: All events filtered to statement period (Apr 1 2025 –
   Mar 3 2026) before summing. Pre-period trades shown separately.

2. **FX conversion**: Non-USD amounts (GBP, HKD) converted to USD using daily
   FX rates from `fmp/fx.py:get_daily_fx_series()`. Per-currency breakdown
   shown in output.

### Results After Fix

| Metric | Before | After |
|--------|--------|-------|
| Approach 1 gap | -$2,695 | **+$1,852** |
| Dividends | $306.97 (gross) | $182.41 (matches statement) |
| Interest | -$308.58 | -$252.40 (matches statement) |
| Pre-period excluded | 0 | 20 trades, $3,874 |
| GBP/HKD FX applied | No | Yes |

### Validated Residual Gap Decomposition (+$1,852)

| Category | Amount | FX? | Notes |
|----------|--------|-----|-------|
| MTM FX aggregation | -$1,661 | YES | Daily HKD→USD vs bulk conversion |
| Fee aggregate dedup | -$145 | NO | -$14.50 = sum of -$10 + -$4.50 (see below) |
| Trade rate timing | -$64 | YES | Our daily close vs IBKR trade-time FX |
| FX translation | -$54 | YES | Statement +$53.88 holding-period FX gain |
| Interest HKD dedup | +$9 | YES | Cross-currency dedup dropped HKD interest |
| Fee rounding | +$63 | ~ | Our -$174 vs stmt Other+Txn -$175 |
| **TOTAL** | **-$1,852** | | |

**95% FX-related ($1,770)**: Inherent to multi-currency accounting methodology.
**5% fee dedup bug ($82)**: Fixable but low priority ($7.45/month).

### MTM FX Aggregation Explained

The $1,661 MTM delta is NOT a bug in our logic. It arises because two
IBKR data sources use different FX methodology:

- **Flex StatementOfFundsLine** (what we ingest): Each daily MHI settlement
  comes with IBKR's own HKD→USD conversion at that day's rate. We keep the
  USD row via cross-currency dedup and sum these daily amounts.
  Result: -$4,918 for MHI.

- **Cash Report** (what we compare against): Sums all MHI settlements in
  HKD first (-25,300 HKD), then converts the aggregate at a single rate
  (~0.1287 = 1 USD/7.77 HKD) → -$3,256 for MHI.

Σ(amount_i × rate_i) ≠ (Σ amount_i) × rate_single (Jensen's inequality).
Our daily-converted approach is more economically accurate — it reflects
actual USD cash impact on each settlement day. The statement's bulk
conversion loses daily FX timing information.

### Fee Aggregate Dedup Bug (Minor)

IBKR reports fee events per segment AND an aggregate row:
- Segment A: -$10.00 (e.g. market data)
- Segment B: -$4.50 (e.g. snapshot)
- Aggregate: -$14.50 (= sum of A+B)

All three have `raw_type=OTHER FEES`, same date, same currency. Our segment
dedup key includes `round(amount, 8)`, so -$10, -$4.50, and -$14.50 are
treated as distinct events. This occurs on 10 of 12 months.

Without aggregates: our fees = -$174.03 vs statement Other+Transaction
fees = -$175.04 (delta $1.01). Low priority to fix.

### Normalizer Validation Summary

After all dedup fixes + diagnostic corrections, our transaction data is
validated against the IBKR statement:

| Category | Our Value | Statement | Match |
|----------|-----------|-----------|-------|
| USD trade sales | $22,303.94 | $22,303.94 | EXACT |
| Dividends (net) | $182.41 | $182.41 | EXACT |
| Interest (USD) | -$252.40 | -$252.40 | EXACT |
| Fees (excl aggregates) | -$174.03 | -$175.04 | $1.01 delta |
| MTM | -$5,250 | -$3,589 | $1,661 FX methodology |

Codex review: Round 1 FAIL → Round 2 PASS.

---

### Next Steps for Issue 1+4

The back-solve approach is viable. Transaction data is now validated clean.

1. **Back-solve starting cash**: `start_cash = observed_end_cash - sum(in_period_fx_converted_impacts)` → approximately -$9,246 (Approach 1), vs statement -$11,097. Gap +$1,852 is the FX aggregation residual.
2. **Seed forward replay**: Pass back-solved starting cash to `derive_cash_and_external_flows()` as `opening_cash_balance`
3. **Exclude FX conversions from cash replay** — same fix needed in `derive_cash_and_external_flows()`
4. **Remaining ~$1.9k gap**: Accept as FX aggregation + truncation error — inherent to multi-currency daily accounting

---

## Cash Back-Solve Implementation (2026-03-05)

### Commits

1. `2c723b8e` — Back-solve starting cash into realized performance NAV
2. `ec946139` — Filter cash anchor by institution/account in back-solve
3. `33100099` — Scope cash anchor by source when institution not explicit

### What Changed

- `_cash_anchor_offset_from_positions()` extracts observed end cash from CUR:* position rows
- Back-solve: `start_cash = observed_end_cash - replay_final_cash`
- Anchor injected at inception date via existing `_apply_cash_anchor()` machinery
- Source-scoped filtering: when `source != "all"` and no explicit `institution`, uses `_provider_matches_from_position_row()` to match cash rows to the target source
- `REALIZED_CASH_ANCHOR_NAV` default flipped to `True`
- `cash_backsolve_*` fields added to `RealizedMetadata` for serialization

### Bug Found and Fixed (Commit 3)

The initial implementation (commit 2) summed CUR:* rows from ALL brokerages
when `institution=None`. For `source="ibkr_flex"`:
- IBKR cash: -$8,723
- Schwab cash: -$16,532
- Merrill cash: -$9,107
- Total (wrong): -$34,362

Commit 3 added source-aware filtering using `_provider_matches_from_position_row()`.

Coincidentally, the old wrong value (-$34,362) combined with a different
`replay_final_cash` produced a similar offset (-$13,368) as the correct
computation (-$8,723 - $4,646 = -$13,369). So the return didn't change.

### Current Results (Post Back-Solve)

| Metric | Before (baseline) | After back-solve |
|--------|-------------------|------------------|
| Total return | -8.50% | +6.37% |
| Annualized | -9.18% | +6.96% |
| Gap vs statement (+0.29%) | -8.79 pp | +6.08 pp |
| Cash anchor applied | No | Yes |
| April return | -25.39% | -20.44% |
| Reconciliation gap | 102.86% | 9.46% |

Back-solve diagnostics:
- `observed_end_cash = -8,723.07` (IBKR only, matches statement -$8,727)
- `replay_final_cash = +4,645.57`
- `back_solved_start_cash = -13,368.65`
- Statement start cash: -$11,097 (gap ~$2.3k, FX + truncation)

### Remaining Gap Analysis (+6.08 pp)

**April is the dominant distortion**:
- Positions: $31,435 → $18,234 (-$13,201, -42% in one month)
- Cash: -$9,386 → -$693 (+$8,694)
- NAV: $22,049 → $17,541 (-$4,508 → -20.44% monthly return)
- Interpretation: Synthetic positions valued at inception then closing in April

**Synthetic position impact**:
- synthetic_enhanced NAV P&L: +$5,911
- observed_only NAV P&L: +$3,179
- Synthetic impact: +$2,732 (positions we don't have real history for)
- Even observed-only return is ~+14.4% (still far from +0.29%)

**Gap breakdown estimate**:

| Driver | Estimated Impact | Fixable? |
|--------|-----------------|----------|
| Synthetic positions (+$2.7k extra P&L) | ~3-4 pp | Partially — better synthetic modeling |
| Cash path shape under truncated history | ~2-3 pp | Hard — no intermediate ground truth |
| 50% data coverage (half positions estimated) | ~1-2 pp | Not without more history |
| FX methodology ($1.9k residual) | ~0.5 pp | Accept — daily vs bulk conversion |

**Conclusion**: The back-solve fixed the biggest structural issue (NAV
denominator). Getting from +6.37% closer to +0.29% requires synthetic
position modeling improvements — specifically, the inception-month
valuation of synthetic positions that then close early in the period.
This is Issue 2 (synthetic cash injection) in the root cause catalog.

### Updated Fix Priority

1. ~~**Issue 1+4** (cash seed)~~: **COMPLETED** — back-solve + source scoping
2. **Issue 2** (synthetic cash injection): Next highest priority. Synthetic
   positions inject phantom cash + position value at inception. April
   distortion is primarily driven by this.
3. **Issue 7** (synthetic futures invisible to NAV): Low impact in current
   IBKR dataset (no synthetic futures currently active).
4. **Issue 3** (first-month dominance): Will improve with Issue 2 fix.
5. **Issue 5** (no intermediate ground truth): Structural limitation.

---

## IBKR Fresh Baseline + Option Pricing + Audit Trail (2026-03-05)

### Context

Shifted to a fresh IBKR-specific reconciliation using a new statement period
(April 1, 2025 – March 3, 2026). Re-downloaded Flex data, re-ingested, and
established a clean comparison baseline.

**IBKR Statement (ground truth):**
- Prior NAV: $22,283.72 (April 1, 2025)
- Current NAV: $22,348.77 (March 3, 2026)
- TWR: +0.291921306%

**Component breakdown (prior/inception):**
- Cash: -$11,097.13
- Stock: $25,089.47
- Options: $8,378.50
- Interest Accruals: -$87.37
- Dividend Accruals: $0.25

### Fix 21: Flex PriorPeriodPosition → Option Price Cache (`d2d3b27a`)

**Plan:** `completed/FLEX_OPTION_PRICING_PLAN.md`

**Root cause:** The realized performance engine valued all 9 options at $0
because `price_cache` had no option price data. IBKR Gateway returns 0 bars
for expired option contracts (tested PLTR P80, PDD C110). The Flex query
already includes `PriorPeriodPosition` with daily closing marks for all held
positions — 614 option rows, 252 business days.

**Implementation:**
1. `ibkr/flex.py` — `normalize_flex_prior_positions()` extracts OPT rows,
   uses `_build_option_symbol()` for ticker matching, multiplies price by
   multiplier (100) to match trade convention
2. `trading_analysis/data_fetcher.py` — threads `ibkr_flex_option_prices`
   through all 3 return paths + `_empty_transaction_payload()`
3. `providers/ibkr_transactions.py` — threads through `fetch_transactions()`
4. `core/realized_performance/_helpers.py` — `_build_option_price_cache()`
   converts flat rows to `{ticker: pd.Series}`
5. `core/realized_performance/engine.py` — Flex-first check in option pricing
   branch (precedence: Flex daily marks > FIFO terminal > IBKR Gateway)
6. `inputs/transaction_store.py` — store/retrieve `flex_option_price_rows`
   using raw JSON pattern (dedup key: `{ticker}:{date}`)
7. `mcp_tools/transactions.py` — `ibkr_flex_option_prices` bucket in
   `provider_rows` + `allowed_providers`

**Effect:** Inception NAV $27,288 → $29,251 (+$1,964 from option pricing).

### Fix 22: Option Expiration Flag in Provider Normalizer

**Root cause:** `providers/normalizers/ibkr_flex.py` did NOT include the
`option_expired` field in its FIFO transaction output. Two normalizer paths:

| Path | Sets `option_expired`? |
|------|----------------------|
| `ibkr/flex.py:371` | Yes |
| `providers/normalizers/ibkr_flex.py` | No (FIXED) |

The transaction store uses the provider normalizer path. All store-ingested
data had `option_expired=False`. The FIFO matcher at line 484 silently drops
transactions with `price == 0 and not is_expiration` — so NMM C70/C85 SELL
events (expired worthless, price=$0) were completely dropped. No
`IncompleteTrade` → no synthetic entry → invisible in position timeline.

**Implementation:**
1. `providers/normalizers/ibkr_flex.py` — Added `option_expired` computation
   (matching `ibkr/flex.py:371` logic) + field in FIFO transaction output
2. DB fix — Updated 12 rows in `normalized_transactions` to set
   `option_expired=TRUE` for all option SELL/COVER at price=0

**Affected options:**
- NMM C70 ($47.50) + NMM C85 ($21.42) — now have synthetic entries at inception
- SLV C30 + SLV C35 — expiration events on 2025-06-20 now correctly flagged

**Effect:** Inception NAV $29,251 → $29,320 (+$68.92 from NMM options).
Option NAV now matches IBKR statement exactly:

| Option | Engine | IBKR | Gap |
|--------|--------|------|-----|
| NMM C70 | $47.50 | $47.50 | $0.00 |
| NMM C85 | $21.42 | $21.42 | $0.00 |
| NXT C30 | $2,812.22 | $2,812.22 | $0.00 |
| PDD C110 | $5,053.60 | $5,053.60 | $0.00 |
| PDD P60 | $443.76 | $443.76 | $0.00 |
| **Total** | **$8,378.50** | **$8,378.50** | **$0.00** |

### Fix 23: Realized Performance Audit Trail

**Plan:** `completed/REALIZED_AUDIT_TRAIL_PLAN.md`

Exposed full audit trail in `debug_inference` output:
- `_serialize_audit_trail()` helper in `engine.py`
- 8 data categories: `synthetic_entries`, `position_timeline`,
  `cash_snapshots`, `observed_cash_snapshots`, `fifo_transactions`,
  `futures_mtm_events`, `synthetic_twr_flows`, `cash_replay_diagnostics_full`
- Threaded through `_postfilter` → aggregation (`audit_trail_by_account`) →
  `_build_inference_diagnostics()` in `mcp_tools/performance.py`

This enabled diagnosis of the NMM C70/C85 bug (discovered via audit trail
showing only SELL events with no synthetic opening).

### Current State (Post Fix 21-23)

**Engine inception NAV breakdown (March 31, 2025):**
- Positions: $33,468
- Cash: -$4,148
- NAV: $29,320

**IBKR statement inception NAV breakdown (April 1, 2025):**
- Stock: $25,089
- Options: $8,379
- Cash: -$11,097
- Other (interest/dividend accruals): -$87
- NAV: $22,284

**Component gaps:**
- Options: **$0 gap** (solved)
- Cash: engine -$4,148 vs IBKR -$11,097 = **+$6,949 gap** (engine cash too high)
- Stock: engine $25,021 vs IBKR $25,089 = **-$68 gap** (minor, likely FX/rounding)
- Total NAV gap: **+$7,036** (engine $29,320 vs IBKR $22,284)

**Remaining gap drivers (all in cash/synthetic territory):**

1. **Synthetic position overvaluation** — 25 synthetic positions with estimated
   cash impact inflate inception NAV. Synthetic entries for positions held
   before the Flex window use cost_basis or current value as price_hint.

2. **Cash anchor accuracy** — Cash replay back-solve seeds at -$4,148 but
   IBKR reports -$11,097. The $6,949 cash gap is the dominant driver.
   Plan exists: `completed/CASH_ANCHOR_NAV_PLAN.md`.

3. **April 2025 -46% month-return** — Positions drop from $33K to $16K.
   When options are sold in April, position value disappears but cash inflow
   may not be captured correctly.

4. **Data coverage 53.85%** — Well below 95% target.

### Updated Fix Priority (Post Fix 21-23)

1. ~~**Option pricing at $0**~~: **FIXED** (Fix 21 + 22). Zero option gap.
2. ~~**Audit trail not visible**~~: **FIXED** (Fix 23). Full event stream in debug output.
3. **Cash anchor gap** ($6,949): Next priority. Cash back-solve produces -$4,148
   but IBKR reports -$11,097. Investigate whether synthetic cash events are
   inflating the replay path.
4. **April position cliff**: Investigate $17K position value drop in one month.
5. **Data coverage**: Structural limitation of ~12-month Flex window.

---

## MTM Summary-Row Dedup Fix (2026-03-05)

### Commit

`4228bc9d` — fix: skip Flex summary rows (accountId="-") in futures MTM normalizer

### Problem

IBKR Flex `StatementOfFundsLine` XML contains two sections: per-account rows
(e.g. `accountId="U2471778"`) and summary/consolidated rows (`accountId="-"`).
These are the same MTM events reported twice. The normalizer's dedup key
includes `account_id`, so rows with different account IDs (`"U2471778"` vs
`"-"`) produced different dedup keys — both passed through, doubling every
MTM event.

This is distinct from the earlier cross-currency dedup fix (`456992fd`), which
handled HKD/USD dual-currency reporting for the same event. This fix handles
the account-section duplication.

### Fix

Added a 2-line guard in `normalize_flex_futures_mtm()` in `ibkr/flex.py`:
```python
if account_id == "-":
    continue
```

Summary rows are always redundant copies of the per-account rows.

### Verification: Exact Match Against IBKR Statement

Fetched live Flex data and compared normalized MTM events against the official
IBKR statement (`U2471778_20250401_20260303.csv`, period Apr 1 2025 – Mar 3 2026).

**After fix**: 83 normalized events, 0 duplicates.

| Contract | Our Events | Our Position MTM | IBKR Statement | Match |
|----------|-----------|-----------------|----------------|-------|
| MGC (MGCM5) | 33 | -$420.00 | -$420.00 | **EXACT** |
| MHI (MHIJ5) | 4 | -$4,353.34 | -$4,353.34 | **EXACT** |
| ZF (ZFM5) | 7 | -$476.56 | -$476.56 | **EXACT** |
| **TOTAL** | **44** | **-$5,249.90** | **-$5,249.90** | **EXACT** |

(Filtered to Apr 1+ to match statement period. Full dataset includes 39
additional pre-April events: MES 4, MGC 17, MHI 12, ZF 6.)

Note: This matches Position MTM only. The statement also reports Transaction
MTM (from trade day, separate from daily settlement). Our normalizer correctly
filters to "Position MTM" activity descriptions only.

### Impact on Current Performance

**None** — `futures_cash_policy` is currently `fee_only`, so MTM events are
not replayed into cash. The fix prevents future double-counting if/when MTM
cash replay is re-enabled.

Current live numbers (2026-03-06):
- TWR: -19.86%
- MWR: 61.33%
- `futures_cash_policy: fee_only`
- `futures_fee_cash_impact_usd: -12.38`

### Tests

12 tests pass (11 existing + 1 new `test_normalize_flex_futures_mtm_skips_summary_section_rows`).

### Updated Normalizer Validation Summary

After all dedup fixes (cross-currency `456992fd` + summary-row `4228bc9d`),
our MTM transaction data is validated against the IBKR statement:

| Category | Our Value | Statement | Match |
|----------|-----------|-----------|-------|
| USD trade sales | $22,303.94 | $22,303.94 | EXACT |
| Dividends (net) | $182.41 | $182.41 | EXACT |
| Interest (USD) | -$252.40 | -$252.40 | EXACT |
| Fees (excl aggregates) | -$174.03 | -$175.04 | $1.01 delta |
| MTM (Apr 1+ period) | -$5,249.90 | -$5,249.90 | **EXACT** |
| Option prices at inception | $8,378.50 | $8,378.50 | EXACT |

---

## Income instrument_type Fix (2026-03-06)

### Commit

`62110090` — fix: income instrument_type misclassified as fx_artifact

### Problem

`normalize_flex_cash_income_trades()` in `ibkr/flex.py:737` hardcoded `instrument_type: "fx_artifact"` for ALL income records (dividends, interest). These represent real securities (NVDA dividends, bond interest) — not FX artifacts. No functional impact today (normalizer intercepts income by `type` field before `instrument_type` is read), but incorrect metadata.

### Fix

- Changed `instrument_type` from `"fx_artifact"` to `"income"` in `ibkr/flex.py:737`
- Added `"income"` to `InstrumentType` + `_VALID_INSTRUMENT_TYPES` in both `ibkr/_types.py` and `trading_analysis/instrument_meta.py`
- Added defensive filter in `nav.py`: skip `"income"` alongside `"fx_artifact"` in cash replay
- Added income-type recognition in `_infer_instrument_type_from_transaction()` in `_helpers.py`

---

## Cash Anchor Cross-Provider Fix (2026-03-06)

### Commits

`3631d766` — fix: cash anchor uses account-alias matching for cross-provider positions

### Problem

`_cash_anchor_offset_from_positions()` in `engine.py:1675-1693` scanned position rows to find current cash balances for NAV back-solve. It filtered by provider `source` — but IBKR transactions come from `ibkr_flex` while IBKR positions come through `snaptrade`. Source matching found zero cash rows → `observed_end_cash = 0` → wrong anchor.

### Root Cause

Cross-provider mismatch: transactions and positions for the same account come from different providers. The cash anchor function assumed they share the same source.

### Fix

Replaced source-based matching with account-alias matching as primary strategy:
1. Build alias set from FIFO transaction `account_id`s using `resolve_account_aliases()` (from existing `TRADE_ACCOUNT_MAP` infrastructure)
2. Match position rows by account identity (e.g., SnapTrade UUID `cb7a1987` ↔ IBKR native `U2471778`)
3. Deduplicate by `(alias_group, ticker)` to prevent double-counting from unconsolidated multi-provider rows
4. Fall back to source/institution matching when no aliases exist or alias matching finds 0 rows
5. `source="all"` preserves existing accept-all behavior

### Results

| Metric | Before | After |
|--------|--------|-------|
| `observed_end_cash` | $0.00 | -$3,648.96 |
| `cash_anchor_offset` | -$4,676.86 | -$8,325.82 |
| `total_return` | -20.05% | -20.05% |

Cash rows are now found (5 non-USD currencies from SnapTrade IBKR account). However, total return is unchanged because SnapTrade doesn't expose IBKR's USD margin balance (~-$8,727 real vs ~-$3,649 reported). The dominant cash component is missing.

### Known Limitation

SnapTrade's `get_user_account_balance` API returns non-USD currency balances for IBKR but NOT the USD cash/margin balance. Observed: CUR:GBP (-$2,109), CUR:HKD (-$87), CUR:CAD (~$0), CUR:JPY (~$0), CUR:MXN (~$0) — total ~-$2,196. Real IBKR total cash: -$8,727. Gap: ~$5,531 of USD cash missing.

### Next Step

Switch to IBKR API for positions (direct position data with accurate cash/margin balances). This is a separate workstream.

### Updated Issue 1+4 Status

Issue 1+4 (cash seed/margin balance) is now partially addressed:
- ✅ Cash anchor back-solve implemented (`946` section)
- ✅ Cross-provider position matching fixed (this section)
- ❌ SnapTrade USD cash gap — requires IBKR API for positions
- ❌ Remaining return gap (-20% vs +0.29%) dominated by missing USD margin data
