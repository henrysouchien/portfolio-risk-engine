# F12 Level 4: Canonical Portfolio Snapshot

## Status: DESIGN NEEDED

12 Codex review rounds across multiple approaches (gross, net, scoped) converged on a root cause: the hedge pipeline has **three independent portfolio state builders** that disagree on cash inclusion, account scope, and exposure denominator. Fixing the short snapshot without aligning these creates preview/execute mismatches.

## The Root Cause

Three paths each build their own "current portfolio":

| Path | Source | Cash | Scope | Denominator |
|------|--------|------|-------|-------------|
| Hedge preview | `ScenarioService` → `PortfolioData` | Included | Whole portfolio | Net (data_objects.py:729) |
| Hedge execute | `_build_rebalance_inputs()` | Excluded | Single account | Net, shorts filtered (hedging.py:156) |
| Trade validation | `_compute_weight_impact()` → `PositionService` | Included | Whole portfolio | Net (trade_execution_service.py:3376) |

A "5% hedge" means different dollar amounts in each path.

## The Fix: Single Canonical Snapshot

Build the portfolio snapshot **once** and pass it through all three paths. This ensures:
- Cash handling is consistent
- Account scoping is consistent
- Denominator is consistent
- Shorts are naturally included (no filtering)

## Design Questions (for next session)

1. **Where should the canonical snapshot live?** Options: a shared function in hedging.py, a PositionService method, or a new PortfolioSnapshot dataclass.

2. **What should the denominator be?** Net or gross? The risk engine normalizes to gross internally. The preview path uses net. Need to pick one and align both.

3. **Should `_compute_weight_impact` use the same snapshot?** Currently it calls PositionService independently. Could accept the snapshot as a parameter instead.

4. **Account scoping**: hedge execute is account-scoped, preview is whole-portfolio. Which is correct? Should preview also be account-scoped?

## What's Already Done (L2 + L3)

- **L2** (`6bd27631`): SHORT trade leg generation, price-drift-safe SELL/SHORT decomposition, basket guard, partial-preview atomicity. 18 tests, 15 Codex rounds.
- **L3** (`0b9ae433`): Broker execution via IBKR, feature flag, DB migration, COVER→BUY mapping, Schwab BUY_TO_COVER, fail-closed provider errors. 45 tests, 17 Codex rounds.
- **Total**: 63 tests, 32 Codex review rounds across L2+L3.

## What L4 Needs to Do

1. Create canonical portfolio snapshot (single source of truth)
2. Thread it through preview, execute, and validation paths
3. Include shorts in the snapshot (remove `value <= 0` filter)
4. Add COVER leg generation to `compute_rebalance_legs()`
5. Remove the 3 preflight guards (hedge route, pre-trade, execute-time)
6. Align denominator across all paths

## Key Files

- `routes/hedging.py` — `_build_rebalance_inputs()`, hedge_preview, hedge_execute
- `mcp_tools/trading_helpers.py` — `compute_rebalance_legs()`
- `services/trade_execution_service.py` — `_validate_pre_trade()`, `_compute_weight_impact()`, existing-short guards
- `services/scenario_service.py` — `analyze_what_if()`
- `portfolio_risk_engine/data_objects.py` — `PortfolioData` weights computation

## Learnings from 12 Review Rounds

- Can't partially switch to gross — creates preview/execute mismatch
- Can't keep net with shorts — weights inflate, but the inflation must be consistent across all paths
- `math.trunc` (not `math.floor`) for negative held quantities
- COVER legs need 4-quadrant logic (held +/- × delta +/-)
- `_validate_pre_trade` concentration cap is a hard error, not just a warning
- `_compute_weight_impact` must use post-trade denominator, not pre-trade
- Basket `_get_portfolio_total_value` must exclude cash to avoid double-counting short proceeds
- Feature flag should gate SHORT legs (generated output), not negative inputs (blocks COVER)
