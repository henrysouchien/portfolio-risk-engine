# Rebalance Trade Generator

## Context

All 7 workflow execution steps need to convert weight changes into a sequenced trade list with share quantities. Today this is manual — the agent/user must compute deltas, calculate shares, and create individual trade orders. This is the highest-leverage cross-cutting gap to close.

The core weight-to-shares math **already exists** in `mcp_tools/basket_trading.py` (`_compute_rebalance_legs`). This plan wraps that logic as a standalone MCP tool that accepts weights from any source (optimization, what-if, manual), not just baskets.

---

## Changes

### 1. New file: `core/result_objects/rebalance.py`

Two dataclasses:

```python
@dataclass
class RebalanceLeg:
    ticker: str
    side: str                          # "BUY" or "SELL"
    quantity: float
    estimated_value: float
    current_weight: float
    target_weight: float
    weight_delta: float
    price: float
    status: str = "computed"           # "computed", "previewed", "preview_failed"
    preview_id: Optional[str] = None   # Set when preview=True and status="previewed"
    error: Optional[str] = None        # Set when status="preview_failed"

@dataclass
class RebalanceTradeResult:
    status: str
    trades: List[RebalanceLeg]
    summary: Dict[str, Any]            # sell_count, buy_count, totals, net_cash
    portfolio_value: float
    residual_cash: float               # Leftover from floor rounding
    skipped_trades: List[Dict]         # Below threshold or missing price
    warnings: List[str]

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Returns agent-consumable snapshot dict.
        Shape: {
            portfolio_value, target_weight_sum, trade_count, sell_count, buy_count,
            total_sell_value, total_buy_value, net_cash_impact,
            residual_cash, skipped_count,
            trades: [{ticker, side, quantity, estimated_value,
            current_weight, target_weight, weight_delta, price, status,
            preview_id, error}], skipped_trades, warnings
        }
        target_weight_sum is the sum of all target weights (used by
        weight_sum_drift flag). skipped_count enables trades_skipped flag.
        """
        ...

    def to_api_response(self) -> Dict[str, Any]:
        """Returns full API response dict.
        Shape: {
            status, analysis_type: "rebalance_trades",
            portfolio_value, summary: {sell_count, buy_count, ...},
            trades: [leg.to_dict() for leg in self.trades],
            skipped_trades, residual_cash, warnings
        }
        Uses make_json_safe() on output.
        """
        ...
```

Mirrors `BasketTradeLeg` pattern from `core/result_objects/basket_trading.py` — includes `status` and `error` fields for per-leg preview tracking. `to_api_response()` follows `BasketTradePreviewResult` envelope pattern with `analysis_type` discriminator.

Add re-exports to `core/result_objects/__init__.py`.

### 2. New file: `core/rebalance_flags.py`

```python
def generate_rebalance_flags(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate interpretive flags from a rebalance agent snapshot.

    Follows established pattern: receives snapshot dict (not result object),
    returns sorted flag list via _sort_flags().
    """
```

Flag types:
- `large_rebalance` (warning) — total trade value > 50% of portfolio
- `high_turnover` (warning) — sum of |weight_delta| > 0.30
- `sell_all_position` (info) — selling entire position
- `trades_skipped` (info) — legs below min threshold
- `price_fetch_failed` (warning) — tickers with missing prices
- `unmanaged_positions` (info) — held positions not in targets (when `unmanaged="hold"`)
- `preview_failures` (error) — some legs have `status="preview_failed"` (when `preview=True`)
- `weight_sum_drift` (info or warning) — target weight sum outside 0.95-1.05 range (info for 0.90-0.95/1.05-1.10, warning for <0.90/>1.10)
- `rebalance_ready` (success) — trade list generated, no errors

Flag function signature: `generate_rebalance_flags(snapshot: dict) -> list[dict]` — receives the snapshot dict from `get_agent_snapshot()`, NOT the result object. This matches the established pattern in `core/optimization_flags.py`, `core/basket_trading_flags.py`, etc. Flags sorted inline by severity (error → warning → info → success) following the same approach used in those modules.

### 3. Promote shared helpers to `mcp_tools/trading_helpers.py`

Extract from `basket_trading.py` into a new shared module:
- `fetch_current_prices(tickers)` — FMP profile endpoint (rename from `_fetch_current_prices`, make public)
- `safe_float(val)` — safe numeric conversion (rename from `_safe_float`)
- `normalize_ticker(ticker)` — strip whitespace/uppercase (rename from `_normalize_ticker`)
- `compute_rebalance_legs(target_weights, portfolio_total, position_values, held_quantities, current_prices)` — core weight→shares math (rename from `_compute_rebalance_legs`, make public)

All four functions promoted to public API. Update `basket_trading.py` to import from the new module. The new `rebalance.py` imports only public API from `trading_helpers.py` — no new private cross-module coupling introduced.

### 4. New file: `mcp_tools/rebalance.py`

```python
@handle_mcp_errors
def generate_rebalance_trades(
    target_weights: Optional[Dict[str, float]] = None,    # Absolute weights (~1.0)
    weight_changes: Optional[Dict[str, float]] = None,    # Signed deltas
    account_id: Optional[str] = None,                     # Filter to specific account
    portfolio_value: Optional[float] = None,              # Override auto-computed total
    unmanaged: Literal["hold", "sell"] = "hold",          # Positions not in targets
    min_trade_value: float = 100.0,                       # Skip dust trades
    preview: bool = False,                                # Stage broker previews
    format: Literal["full", "agent"] = "full",
    user_email: Optional[str] = None,
) -> dict:
```

**Validation:**
- Exactly one of `target_weights` or `weight_changes` required
- `target_weights` values must be >= 0.0 (no short/negative weights in v1). Note: `weight_changes` values are signed deltas and MAY be negative (to reduce a position)
- `target_weights` sum validation (warning-only, no rejection):
  - Sum < 0.90 or > 1.10: emit `weight_sum_drift` warning flag with actual sum
  - Sum 0.90-0.95 or 1.05-1.10: emit `weight_sum_drift` info flag
  - Sum 0.95-1.05: no flag (clean)
  - Rationale: match `baskets.py` warning-only pattern; intentional high-cash or partial-target sets are valid use cases
- After `weight_changes` delta application, resulting target weights are clamped to >= 0.0 (negative result means "sell all")
- `preview=True` requires `account_id` — error if omitted (multi-account preview is not supported; consolidated positions can't be routed to a single broker account)

**Data flow:**
1. Resolve user → load positions via `PositionService.get_all_positions(consolidate=False, account=account_id)` first to get raw (pre-consolidation) positions. **Empty position check**: if no positions returned, return early with `status="error"` and message "No positions found" (or "No positions found for account {account_id}"). This avoids the consolidation code raising on empty input. Then call `get_all_positions(consolidate=True, account=account_id)` for the actual weight computation. (Alternative: wrap in try/except for the empty-consolidation edge, but explicit check is cleaner.)
3. Exclude cash/CUR positions from weight computation
4. Compute current weights: `{ticker: value / total_value}`
5. If `weight_changes`: apply deltas to current weights → `target_weights`. Clamp resulting weights to >= 0.0
6. If `unmanaged="sell"`: add weight=0 for held tickers not in targets
7. Fetch current prices via `fetch_current_prices()` from trading_helpers
8. Build position_values and held_quantities dicts from positions
9. Call `compute_rebalance_legs()` from trading_helpers → raw legs list (sells first)
10. Filter legs below `min_trade_value`, enrich with weight info → `RebalanceLeg` objects (status="computed")
11. If `preview=True`: call `TradeExecutionService.preview_order()` per leg. On success: set `status="previewed"`, `preview_id=<id>`. On failure: set `status="preview_failed"`, `error=<message>`
12. Build `RebalanceTradeResult` with summary stats

**Agent format wiring** (in `mcp_tools/rebalance.py`):
```python
def _build_agent_response(result: RebalanceTradeResult) -> dict:
    snapshot = result.get_agent_snapshot()
    flags = generate_rebalance_flags(snapshot)  # from core/rebalance_flags.py
    return {
        "status": result.status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
    }
```

Follows established pattern: `snapshot = result.get_agent_snapshot()` → `flags = generate_*_flags(snapshot)` → compose response. Matches `mcp_tools/optimization.py`, `mcp_tools/basket_trading.py`, etc.

When `format="full"`: return `result.to_api_response()`. When `format="agent"`: return `_build_agent_response(result)`.

**Reuses from `mcp_tools/trading_helpers.py` (new shared module):**
- `compute_rebalance_legs()` — core weight→shares math (promoted from `_compute_rebalance_legs`)
- `fetch_current_prices()` — FMP profile endpoint
- `safe_float()`, `normalize_ticker()` — helpers

### 5. Register in `mcp_server.py`

Add import + `@mcp.tool()` wrapper following existing pattern. Docstring:

> Generate a sequenced trade list to rebalance portfolio to target weights.
> Accepts target weights from any source (optimization, what-if, manual) and
> converts them into actionable BUY/SELL legs with share quantities.
> Sells sequenced before buys to free buying power.

---

## Files Changed

| File | Change |
|------|--------|
| `core/result_objects/rebalance.py` | NEW — RebalanceLeg + RebalanceTradeResult (with get_agent_snapshot, to_api_response) |
| `core/result_objects/__init__.py` | Add re-exports |
| `core/rebalance_flags.py` | NEW — generate_rebalance_flags(snapshot) + 8 flag types |
| `mcp_tools/trading_helpers.py` | NEW — promoted public helpers (compute_rebalance_legs, fetch_current_prices, safe_float, normalize_ticker) |
| `mcp_tools/basket_trading.py` | Update imports to use trading_helpers (delete private copies) |
| `mcp_tools/rebalance.py` | NEW — generate_rebalance_trades() MCP tool + _build_agent_response() |
| `mcp_server.py` | Register tool |
| `tests/core/test_rebalance_flags.py` | NEW — flag generation tests |
| `tests/mcp_tools/test_rebalance_agent_format.py` | NEW — agent format + MCP tool tests |

---

## Key Design Decisions

1. **Separate file from basket_trading** — conceptually distinct (arbitrary weights vs. basket CRUD), imports shared helpers
2. **`account_id` optional for compute, required for preview** — without it, uses consolidated positions for weight computation. With it, filters before consolidation via `PositionService.get_all_positions(account=account_id)`. Preview requires `account_id` because `TradeExecutionService.preview_order()` needs a concrete tradeable account
3. **`unmanaged="hold"` default** — positions not in target_weights are left alone. Set to `"sell"` for full-portfolio rebalances from optimization
4. **No tax-lot integration in v1** — sells specify quantity only, broker uses FIFO. Future: chain `suggest_tax_loss_harvest()` output
5. **`preview=True` returns preview_ids** that feed directly into existing `execute_basket_trade(preview_ids=[...])`. No new execution tool needed
6. **`min_trade_value=100`** — skip dust trades below $100 to avoid noise
7. **Per-leg status/error fields** — mirrors `BasketTradeLeg` pattern. Enables `preview_failures` flag to reference specific failed legs
8. **Shared helpers promoted to public API** — `trading_helpers.py` with public names. `rebalance.py` imports only public API — no new private cross-module coupling. `basket_trading.py` updated to import from shared module
9. **Weight validation is warning-only** — matches `baskets.py` pattern. No hard rejection. Intentional high-cash or partial-target sets are valid (e.g., "invest 60% of portfolio in these 5 stocks, hold rest as-is")
10. **No negative target weights** — v1 is long-only rebalancing. `target_weights` values must be >= 0.0. `weight_changes` values MAY be negative (signed deltas). After delta application, results clamped to >= 0.0
11. **Flags receive snapshot, not result object** — `generate_rebalance_flags(snapshot)` matches established `generate_*_flags(snapshot)` pattern across all flag modules
12. **Empty position early-exit** — account filtering can produce empty position sets. Check with `consolidate=False` first to avoid `PositionService` raising on empty-consolidation. Return clean error before any computation
13. **Snapshot includes `target_weight_sum`** — enables `weight_sum_drift` flag to compute severity tiers from snapshot alone (no result object needed)

---

## Verification

### 1. Flag tests (`tests/core/test_rebalance_flags.py`)
- `large_rebalance` triggers when trade value > 50% portfolio
- `high_turnover` triggers when sum |weight_delta| > 0.30
- `sell_all_position` triggers for full position liquidation
- `trades_skipped` triggers when legs filtered by min_trade_value
- `price_fetch_failed` triggers for missing prices
- `unmanaged_positions` triggers when held tickers not in targets
- `preview_failures` triggers when any leg has status="preview_failed"
- `rebalance_ready` emitted on clean generation
- `weight_sum_drift` triggers for out-of-range weight sums

### 2. Agent format + MCP tool tests (`tests/mcp_tools/test_rebalance_agent_format.py`)
- target_weights mode: buy/sell/mixed legs, correct share quantities
- weight_changes mode: delta application, new positions via delta
- unmanaged="hold" vs "sell"
- min_trade_value filtering
- Missing prices → skip with warning
- Cash/CUR positions excluded
- Sell capped to held quantity
- portfolio_value override vs auto-compute
- Agent format snapshot shape: `{status, format, snapshot, flags}`
- Full format response shape: `{status, analysis_type, portfolio_value, summary, trades, ...}`
- preview=True without account_id → error
- preview=True with account_id → leg status/preview_id populated
- Empty position set → clean error return
- Weight sum drift: info flag (0.90-0.95), warning flag (<0.90)
- Negative weight rejection

### 3. Integration test (manual)
Call with real portfolio positions, verify trade list makes sense. Compare output to manually computed expected trades.

### 4. MCP test
After `/mcp` reconnect, verify `generate_rebalance_trades` appears in tool list. Call with `target_weights` from a `run_optimization()` result.
