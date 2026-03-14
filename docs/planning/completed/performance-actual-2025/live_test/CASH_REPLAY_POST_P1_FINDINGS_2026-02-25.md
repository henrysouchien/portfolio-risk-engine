# Cash Replay Post-P1 Findings (2026-02-25)

## Scope
Focused diagnostic after implementing `docs/planning/CASH_REPLAY_P1_FIX_PLAN.md`, with emphasis on March/April 2025 futures periods and remaining realized-return distortion.

Inputs used:
- Live full outputs saved on 2026-02-25:
  - `system_output_all_live_full_post_p1.json`
  - `system_output_ibkr_flex_live_full_post_p1.json`
  - `system_output_schwab_live_full_post_p1.json`
  - `system_output_plaid_live_full_post_p1.json`
- Event-level replay trace generated from current code path:
  - `cash_replay_post_p1_trace.json`
- Broker baseline:
  - `../baseline_extracted_data.json`

## Major Findings

1. P1 logic is active in live runs.
- IBKR/all runs now emit cash replay warnings:
  - `Cash replay: skipped 4 fx-artifact transaction(s).`
  - `Cash replay: replaying 12 futures transaction(s); inference is suppressed while futures exposure is open.`
  - `Cash replay: 2 open futures position(s) at end of replay (MES, MGC).`
- This confirms filter + futures-gating behavior is executing.

2. Inference injections are not the current distortion driver.
- `flow_source_breakdown.inferred = 0` for `all`, `schwab`, `plaid`, `ibkr_flex`.
- `inferred_flow_diagnostics.total_inferred_event_count = 0` in current full outputs.
- Provider-authoritative flow mode is dominating (`provider_authoritative_applied` > 0, `inferred` = 0).

3. Returns remain wildly wrong versus broker baselines.
- Baseline broker-reported TWR (2025):
  - IBKR: `-9.353273068%`
  - Schwab acct 165: `-8.29%` (other Schwab accounts: `-14.69%`, `+10.65%`)
- Current live system output (post-P1):
  - `all`: `+83.91%`
  - `ibkr_flex`: `+126.32%`
  - `schwab`: `+142.79%`
  - `plaid`: `+1.32%`

4. Event-level evidence shows futures full-notional cash replay still dominates NAV.
- In `cash_replay_post_p1_trace.json`, IBKR futures legs create large synthetic cash swings:
  - 2025-03-21 `ZF BUY 1000`: `delta_std = -108,165.58`
  - 2025-04-09 `ZF SELL 1000`: `delta_std = +108,201.60`
  - 2025-04-14 `MGC BUY 10`: `delta_std = -32,259.87`
  - 2025-05-28 `MGC SELL 10`: `delta_std = +32,979.13`
- Month-end cash (standard replay) versus fee-only futures sensitivity replay:
  - `ibkr_flex`:
    - 2025-03: `-75,717.78` vs `+2,863.29` (diff `-78,581.07`)
    - 2025-04: `+39,244.03` vs `+16,470.92` (diff `+22,773.11`)
    - 2025-05: `+72,143.10` vs `+16,389.99` (diff `+55,753.11`)
  - `all`:
    - 2025-03: `-68,813.09` vs `+9,769.99` (diff `-78,583.08`)
    - 2025-04: `+38,401.72` vs `+15,630.63` (diff `+22,771.09`)
    - 2025-05: `+72,299.84` vs `+16,548.75` (diff `+55,751.09`)

Interpretation: suppressing inferred contributions during open futures windows avoids one failure mode, but full-notional futures cash still feeds directly into month-end cash/NAV and is large enough to drive the extreme returns.

5. Secondary signal: potential double-counting between income and non-external provider flows.
- For `ibkr_flex`, authoritative provider flows are all non-external (`50/50`, external `0`).
- There are repeated same-date/same-amount matches between `INCOME` and `PROVIDER_FLOW` rows (25 matches, net `-395.04` by simple match heuristic).
- This is smaller than futures notional distortion, but likely still contaminates cash/NAV.

## What P1 solved vs not solved

Solved/verified:
- UNKNOWN/fx-artifact replay filters are implemented and working.
- Futures exposure gating of inference is implemented and working.

Not solved:
- Realized return magnitude remains far from broker truth.
- Dominant remaining issue appears to be **futures cash modeling itself** (full notional in cash replay), not inferred external-flow injection.

## Recommended Next Investigation

1. Implement a futures-specific cash model for replay (variation-margin style) so futures notional does not flow through cash/NAV as equity-like notional.
2. Keep futures P&L preserved, but decouple from notional cash movement at event replay time.
3. Audit and dedupe overlap between `income_with_currency` and non-external `provider_flow_events` for providers where both are present (starting with IBKR).
4. Re-run live comparison against baseline TWR after #1/#3 and validate March/April spikes are removed.
