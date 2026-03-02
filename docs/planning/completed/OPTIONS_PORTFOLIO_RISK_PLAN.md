# Options Portfolio Risk Integration

## Context

The portfolio system has full options trading analysis (`options/greeks.py`, `options/chain_analysis.py`) and option chain MCP tools, but option **positions** in the portfolio view have no Greeks or expiry-awareness. A portfolio with 35% in options shows them as flat equity-like positions — no delta, gamma, theta, vega, no expiry warnings. This plan adds option position enrichment and aggregate portfolio Greeks, following the proven futures integration pattern.

## What This Adds

1. **Position enrichment**: Parse option symbols → add `option_type`, `strike`, `expiry`, `underlying`, `days_to_expiry` to each option position
2. **Expiry flags**: Near-expiry (≤7 days) and expired position warnings
3. **Portfolio Greeks summary**: Aggregate delta, gamma, theta, vega across all option positions (dollar-weighted)
4. **Greeks flags**: Theta drain warning, significant net delta, high vega exposure

## Phase 1: Option Position Enrichment

### 1a. `enrich_option_positions()` in `services/position_enrichment.py`

New function following the `enrich_futures_positions()` pattern (in-place mutation of position dicts).

**Detection**: Check `type == "option"` on position dict first (primary), then fall back to `parse_option_contract_identity_from_symbol()` for symbol-pattern matching (catches positions without explicit type).

**For each detected option position:**
- Parse symbol via `parse_option_contract_identity_from_symbol()` from `trading_analysis/symbol_utils.py`
- If parser returns `None` (unparseable symbol format): set `is_option: True`, `option_parse_failed: True`, skip remaining fields. Position will be counted in exposure but excluded from Greeks computation.
- Otherwise add fields: `option_type` (call/put), `strike`, `expiry` (date string), `underlying`, `days_to_expiry` (int), `is_option: True`

**Note on SnapTrade**: Current SnapTrade normalization (`snaptrade_loader.py:1055`) excludes options from the main holdings endpoint. Option enrichment will only fire for Schwab and IBKR Flex positions initially. SnapTrade option support is a separate backlog item.

**Call sites** — same 3 locations as `enrich_futures_positions()` in `services/position_service.py`:
- Line ~209 (Schwab positions)
- Line ~258 (SnapTrade positions)
- Line ~340 (consolidated positions)

### 1b. `options_exposure` in `get_exposure_snapshot()`

Add to `core/result_objects/positions.py` `PositionResult.get_exposure_snapshot()`:

```python
"options_exposure": {
    "option_count": 5,
    "calls": 3,
    "puts": 2,
    "nearest_expiry": "2026-03-15",
    "nearest_expiry_days": 15,
    "by_underlying": {"AAPL": 3, "SPY": 2}
}
```

### 1c. Position flags in `core/position_flags.py`

| Flag | Severity | Condition |
|------|----------|-----------|
| `near_expiry_options` | warning | Any option position with ≤7 DTE |
| `expired_options` | error | Any option position with DTE ≤ 0 |
| `options_concentration` | info | Options > 20% of portfolio by market value |

### Key files modified (Phase 1)
| File | Change |
|------|--------|
| `services/position_enrichment.py` | New `enrich_option_positions()` function (~40 lines) |
| `services/position_service.py` | Add calls at 3 enrichment sites |
| `core/result_objects/positions.py` | Add `options_exposure` to `get_exposure_snapshot()` |
| `core/position_flags.py` | Add 3 option flags |

## Phase 2: Portfolio Greeks Aggregation

### 2a. New `options/portfolio_greeks.py`

**`PortfolioGreeksSummary` dataclass:**
```python
@dataclass
class PortfolioGreeksSummary:
    total_delta: float          # Dollar delta (sum of position deltas × qty × multiplier × underlying_price)
    total_gamma: float          # Dollar gamma
    total_theta: float          # Daily theta in dollars (negative = decay cost)
    total_vega: float           # Dollar vega per 1% IV move
    position_count: int         # Number of option positions with Greeks
    failed_count: int           # Positions where Greeks couldn't be computed
    by_underlying: dict         # Per-underlying Greeks breakdown
    source: str                 # "computed" or "ibkr_live"
```

**`compute_portfolio_greeks(positions, risk_free_rate=None) → PortfolioGreeksSummary`:**

For each option position (skip if `option_parse_failed` is set):
1. Extract `strike`, `expiry`, `option_type`, `underlying` from enriched position (Phase 1)
2. Get underlying price from position data (prefer `current_price` on position dict if available, else `latest_price()` — note `latest_price()` uses month-end close which can be stale for near-expiry options; log a warning when DTE < 7 and using month-end price)
3. Compute per-contract Greeks via `black_scholes_greeks()` from `options/greeks.py`
4. Scale to dollar Greeks (standard multiplier = 100 for US equity options; use position's `multiplier` field if present for non-standard contracts):
   - **Dollar delta**: `delta × signed_quantity × multiplier × underlying_price` (exposure per $1 move)
   - **Dollar gamma**: `gamma × signed_quantity × multiplier × underlying_price²` (delta change per $1 move in underlying; gamma is ∂²V/∂S², multiply by S² to get dollar terms)
   - **Dollar theta**: `theta × signed_quantity × multiplier` (daily P&L from time decay, already in $ per contract)
   - **Dollar vega**: `vega × signed_quantity × multiplier` (P&L per 1% IV move, already in $ per contract)
5. Sum across all positions. Signed quantity preserves short positions (negative qty → negative delta for short calls, etc.)
6. Track `failed_count` for positions where Greeks computation raises (e.g., expired option, zero time to expiry)

**IBKR live Greeks path** (preferred when TWS connected):
- Use `fetch_snapshot(contracts)` from `ibkr/market_data.py` — it already sets `genericTickList` internally for options (line ~582), caller does NOT pass it
- `fetch_snapshot()` returns per-contract results with possible errors/timeouts — fallback to computed Greeks must be **per-position**, not global
- If TWS is not connected or `fetch_snapshot` raises, fall back to computed path for all positions

**Risk-free rate**: Use `get_treasury_rate()` from existing provider, default 0.05 if unavailable.

### 2b. Wire into exposure snapshot + MCP layer

**Core layer** — add `portfolio_greeks` to `get_exposure_snapshot()` in `core/result_objects/positions.py` (consistent with `futures_exposure` pattern at line ~647):

```python
# In get_exposure_snapshot(), after futures_exposure section:
option_positions = [p for p in positions if p.get("is_option")]
if option_positions:
    from options.portfolio_greeks import compute_portfolio_greeks
    greeks_summary = compute_portfolio_greeks(option_positions)
    snapshot["portfolio_greeks"] = greeks_summary.to_dict()
```

**MCP layer** — `_build_agent_response()` in `mcp_tools/positions.py` already calls `get_exposure_snapshot()`, so Greeks flow through automatically. No additional MCP wiring needed.

### 2c. Greeks flags in `core/option_portfolio_flags.py`

New flag file (follows pattern of other `core/*_flags.py` files):

| Flag | Severity | Condition |
|------|----------|-----------|
| `theta_drain` | warning | `total_theta < -$50/day` (portfolio losing >$50/day to time decay) |
| `significant_net_delta` | info | `abs(total_delta) > 20% of portfolio value` |
| `high_vega_exposure` | warning | `abs(total_vega) > 5% of portfolio value` |
| `greeks_computation_failures` | info | `failed_count > 0` |

### Key files modified (Phase 2)
| File | Change |
|------|--------|
| `options/portfolio_greeks.py` | **New file** — `PortfolioGreeksSummary` + `compute_portfolio_greeks()` (~150 lines) |
| `core/result_objects/positions.py` | Wire Greeks into `get_exposure_snapshot()` (~10 lines) |
| `core/option_portfolio_flags.py` | **New file** — 4 Greeks flags (~50 lines) |

## Reused Infrastructure

| Component | File | Reuse |
|-----------|------|-------|
| `black_scholes_greeks()` | `options/greeks.py` | Per-contract Greeks computation |
| `implied_volatility()` | `options/greeks.py` | IV solver for computed path |
| `parse_option_contract_identity_from_symbol()` | `trading_analysis/symbol_utils.py` | Symbol → (underlying, strike, expiry, right) |
| `enrich_futures_positions()` | `services/position_enrichment.py` | Pattern template for option enrichment |
| `get_exposure_snapshot()` | `core/result_objects/positions.py` | Extend with options_exposure section |
| Position flags pattern | `core/position_flags.py` | Template for option flags |
| `GreeksSnapshot` | `options/result_objects.py` | Existing Greeks dataclass |
| `fetch_snapshot()` | `ibkr/market_data.py` | Live Greeks from IBKR (optional) |

## What This Does NOT Do

- Does NOT change risk analysis pipeline (no Greeks in factor model — that's a separate effort)
- Does NOT add options to performance attribution (already works via pricing chain)
- Does NOT handle complex multi-leg strategy detection (existing `analyze_option_strategy` tool covers that)
- Does NOT change portfolio value calculation (options already valued at market price)

## Verification

1. **Unit tests**: `tests/options/test_portfolio_greeks.py` — mock positions with known Greeks, verify aggregation math
2. **Enrichment tests**: `tests/services/test_position_enrichment.py` — verify option fields added correctly
3. **Flag tests**: `tests/core/test_option_portfolio_flags.py` — verify flag thresholds
4. **Live MCP test**: `get_positions(format="agent")` with option positions → verify `portfolio_greeks` section and flags appear
5. **Edge cases**: Portfolio with no options (no Greeks section), expired options (DTE=0), missing underlying price (graceful skip), unparseable option symbols (counted in exposure but excluded from Greeks with `failed_count`), short option positions (negative quantity preserved in dollar Greeks), IBKR per-position fallback (one position times out → computed fallback for that position only)
