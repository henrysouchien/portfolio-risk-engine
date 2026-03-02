# Leverage-Aware Concentration Flag

## Context

`core/position_flags.py` computes concentration percentages using `gross_non_cash` (sum of absolute position values) as the denominator. This is the correct portfolio construction convention — a position's weight in the gross book is the standard metric. However, for levered portfolios, this masks the risk-to-capital impact. A position at 35% of net equity shows as ~23% of the 1.5x gross book, understating how much of the investor's capital is at risk in a single name.

Rather than changing the base denominator (which would break consistency with weights shown everywhere else), we add a **`leveraged_concentration` flag** that fires only when leverage > 1.1x AND a single-issuer position exceeds 25% of net equity (`portfolio_total`).

## Implementation

### `core/position_flags.py`

**1. Move leverage computation earlier** (currently lines 142-155, move to after line 94)

The net_exposure/gross_exposure/leverage calculation currently runs after the concentration block. Move it to right after `gross_non_cash` so `leverage` is available for the new flag. The leverage *flag appends* (`leveraged`, `high_leverage`) stay in their current position.

**2. Add `leveraged_concentration` flag** (after existing `single_position_concentration` loop, ~line 109)

Inside the `if gross_non_cash > 0:` guard, after the single-stock concentration loop:

```python
if leverage > 1.1 and portfolio_total > 0:
    for position in single_issuer:
        ticker = str(position.get("ticker", "UNKNOWN"))
        abs_value = abs(_to_float(position.get("value", 0)))
        equity_weight = abs_value / portfolio_total * 100.0
        if equity_weight > 25.0:
            flags.append({
                "type": "leveraged_concentration",
                "severity": "warning",
                "message": (
                    f"{ticker} is {equity_weight:.0f}% of net equity "
                    f"({abs_value / gross_non_cash * 100.0:.0f}% of gross exposure)"
                ),
                "ticker": ticker,
                "equity_weight_pct": round(equity_weight, 1),
                "gross_weight_pct": round(abs_value / gross_non_cash * 100.0, 1),
                "leverage": round(leverage, 2),
            })
```

**Threshold: 25% of net equity.** At 1.5x leverage, a 25% equity position is ~17% gross — below the existing 15% gross threshold, so this catches positions that slip through. The message shows both perspectives so the agent understands the situation.

**Only fires when leverage > 1.1x** — for unleveraged portfolios, `gross_non_cash ≈ portfolio_total` and the existing concentration flags are sufficient. Strict `>` is intentional — exactly 1.1x is borderline and shouldn't flag.

**Strict `> 25.0` threshold** — exactly 25.0% is borderline and doesn't flag. Consistent with other threshold checks in the file (all use strict `>`).

**Guard: `portfolio_total > 0`** — if net equity is zero or negative, the equity weight calculation is meaningless. The flag is skipped entirely. This is already in the condition (`portfolio_total > 0`).

**Only iterates over `single_issuer`** — ETFs/funds are excluded via `_is_diversified()`, consistent with the existing `single_position_concentration` flag.

**Double-flagging is intentional.** A position can trigger both `single_position_concentration` (>15% of gross) AND `leveraged_concentration` (>25% of equity). Both are useful — gross weight shows portfolio construction, equity weight shows capital risk. No dedup needed.

### `tests/core/test_position_flags.py`

8 new tests:

1. **`test_leveraged_concentration_fires_when_levered`** — 1.5x leverage, position at 35% of equity (23% gross) → flag fires with both weights in message
2. **`test_leveraged_concentration_skipped_when_unleveraged`** — No leverage, position at 30% of equity → no `leveraged_concentration` flag
3. **`test_leveraged_concentration_below_threshold`** — 1.5x leverage, position at 20% of equity → no flag
4. **`test_leveraged_concentration_message_shows_both_weights`** — Verify `equity_weight_pct` and `gross_weight_pct` fields present and correct
5. **`test_leveraged_concentration_excludes_diversified`** — ETF at 30% of equity with leverage → no flag (uses `single_issuer` list, not `diversified`)
6. **`test_leveraged_concentration_exactly_at_boundary`** — Exactly 1.1x leverage and exactly 25.0% equity → no flag (strict `>`)
7. **`test_leveraged_concentration_negative_total_value`** — Negative `total_value` (net equity <= 0) → no flag (guard: `portfolio_total > 0` uses `abs()` so this tests the edge)
8. **`test_leveraged_concentration_coexists_with_single_position`** — Position triggers both `single_position_concentration` and `leveraged_concentration` → both flags present (intentional double-flagging)

### Files Modified

| File | Change |
|------|--------|
| `core/position_flags.py` | Move leverage calc earlier (~0 net lines), add `leveraged_concentration` flag (~12 lines) |
| `tests/core/test_position_flags.py` | Add 8 tests (~80 lines) |

### What's NOT Changed

- Existing `single_position_concentration` flag (15% of gross) — unchanged
- `compute_herfindahl()` in `portfolio_risk.py` — stays gross-normalized
- Risk score limit checks — stays gross-normalized
- Top-5 and fund concentration flags — stay gross-denominated

## Verification

1. `pytest tests/core/test_position_flags.py -v` — all existing + new tests pass
2. `get_positions(format="agent")` via MCP — verify `leveraged_concentration` flag appears for current portfolio (1.5x levered, DSU at ~35% of equity)
3. Verify existing flags unchanged (no regressions)
