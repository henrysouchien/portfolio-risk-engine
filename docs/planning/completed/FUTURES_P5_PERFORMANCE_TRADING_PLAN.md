# Futures Phase 5: Performance + Trading

## Context

Futures P&L in the trading pipeline is **already numerically correct** because IBKR Flex pre-multiplies quantity by the contract multiplier (line 346-347 of `ibkr/flex.py`). However, the system doesn't know it's dealing with futures contracts — it sees "500 units" instead of "10 ES contracts × 50 multiplier". This phase adds contract-level attribution, populates the existing (but empty) futures metadata fields, and adds futures-specific trading flags.

**What this phase does:**
- Preserve original contract quantity + multiplier on trade objects for display/attribution
- Add `instrument_type` and `is_futures` fields to `ClosedTrade`, `OpenLot`, `IncompleteTrade`
- Populate existing `RealizedMetadata` futures fields (lines 144-149 of `realized_performance.py`)
- Add futures-specific trading flags (contract-level P&L, notional concentration)
- Futures segment breakdown in trading agent snapshot (futures vs equity P&L)

**What this phase does NOT do:**
- Change P&L calculation (already correct via pre-multiplied qty)
- Roll tracking / expiry awareness (Phase 6)
- Add multiplier to non-IBKR normalizers (Plaid/SnapTrade/Schwab don't have futures)

## Changes

### 1. FIFO Dataclasses — `trading_analysis/fifo_matcher.py`

Add metadata fields to all three trade dataclasses. These are display/attribution only — P&L math stays unchanged.

**OpenLot** (line 27):
```python
@dataclass
class OpenLot:
    ...
    direction: str = "LONG"
    # NEW: Futures attribution
    instrument_type: str = "equity"     # "equity" | "futures" | "option"
    multiplier: float = 1.0             # Contract multiplier (50 for ES, 1.0 for equities)
    contract_quantity: Optional[float] = None  # Original qty before multiplier (None = same as quantity)
```

**ClosedTrade** (line 56):
```python
@dataclass
class ClosedTrade:
    ...
    exit_transaction_id: Optional[str] = None
    # NEW: Futures attribution
    instrument_type: str = "equity"
    multiplier: float = 1.0
    contract_quantity: Optional[float] = None  # Original contracts traded
```

**IncompleteTrade** (line 122):
```python
@dataclass
class IncompleteTrade:
    ...
    direction: str = "LONG"
    # For manual backfill
    manual_entry_date: Optional[datetime] = None
    manual_entry_price: Optional[float] = None
    # NEW: Futures attribution (after manual_entry_price, the actual last field)
    instrument_type: str = "equity"
    multiplier: float = 1.0
    contract_quantity: Optional[float] = None
```

**Threading through FIFOMatcher methods** — The `txn` dict is available in `process_transactions()` but not passed to `_process_entry`/`_process_exit`/`_create_incomplete_trade`. Two approaches:

**Option A (preferred):** Extract futures metadata from `txn` in `process_transactions()` at the top of the loop (line 374) and pass to each method via a new `txn_meta` dict parameter:

```python
# In process_transactions(), after extracting symbol/quantity/price/etc (line 374):
txn_meta = {
    "instrument_type": txn.get("instrument_type", "equity"),
    "contract_identity": txn.get("contract_identity"),
}
```

Then pass `txn_meta` to `_process_entry()`, `_process_exit()`, and `_create_incomplete_trade()`.

**Option B:** Pass the entire `txn` dict to each method. Less clean but simpler diff.

Either way, the metadata flows into OpenLot/ClosedTrade/IncompleteTrade creation at these sites:
- `_process_entry()` line 500 → `OpenLot()`
- `_process_exit()` lines 545, 577 → `ClosedTrade()`
- `_process_exit()` line 601 → inline `IncompleteTrade()`
- `_create_incomplete_trade()` line 675 → `IncompleteTrade()`

### 2a. TradeResult Metadata — `trading_analysis/models.py`

**Critical:** The agent snapshot (`get_agent_snapshot()`, line 623) uses `TradeResult` objects (line 267), NOT `ClosedTrade` directly. `TradeResult` currently has: `symbol, entry_date, exit_date, days_in_trade, avg_buy_price, avg_sell_price, units_bought, units_sold, cost_basis, proceeds, pnl_dollars, pnl_percent, win_score, grade, status, name, currency, direction, num_buys, num_sells, pnl_dollars_usd`.

Add new fields to `TradeResult` (line 267):
```python
@dataclass
class TradeResult:
    ...
    pnl_dollars_usd: float = 0.0
    # NEW: Futures attribution
    instrument_type: str = "equity"
    multiplier: float = 1.0
    contract_quantity: Optional[float] = None
```

### 2b. Thread TradeResult Metadata from ClosedTrade — `trading_analysis/analyzer.py`

**Where:** `_analyze_trades_fifo()` (line 597) creates `TradeResult` from `ClosedTrade`. Thread the new fields:

```python
trade_results.append(TradeResult(
    ...,
    num_buys=1,
    num_sells=1,
    # NEW:
    instrument_type=getattr(closed, "instrument_type", "equity"),
    multiplier=getattr(closed, "multiplier", 1.0),
    contract_quantity=getattr(closed, "contract_quantity", None),
))
```

The legacy `_analyze_trades_averaged()` (line 691) does not need changes — it doesn't handle futures.

### 2c. Agent Snapshot Futures Breakdown — `trading_analysis/models.py`

**Where:** `FullAnalysisResult.get_agent_snapshot()` (~line 623)

The snapshot already iterates `self.trade_results` (which are `TradeResult` objects). Add a `futures_breakdown` section when futures trades exist:

```python
# After computing top_winners/top_losers, before return:
futures_trades = [t for t in closed_trades if getattr(t, "instrument_type", "equity") == "futures"]
if futures_trades:
    equity_trades = [t for t in closed_trades if getattr(t, "instrument_type", "equity") != "futures"]
    snapshot["futures_breakdown"] = {
        "futures_trade_count": len(futures_trades),
        "futures_pnl_usd": round(sum(self._effective_pnl_usd(t) for t in futures_trades), 2),
        "equity_trade_count": len(equity_trades),
        "equity_pnl_usd": round(sum(self._effective_pnl_usd(t) for t in equity_trades), 2),
        "futures_win_rate_pct": round(
            sum(1 for t in futures_trades if self._effective_pnl_usd(t) > 0) / len(futures_trades) * 100, 1
        ) if futures_trades else None,
    }
```

Also enrich `top_winners`/`top_losers` dicts with `instrument_type` and `contract_quantity`:

```python
{
    "symbol": trade.symbol,
    "pnl_usd": round(self._effective_pnl_usd(trade), 2),
    "pnl_pct": round(trade.pnl_percent, 2),
    "direction": trade.direction,
    "instrument_type": getattr(trade, "instrument_type", "equity"),  # NEW
    "contract_quantity": getattr(trade, "contract_quantity", None),   # NEW
}
```

### 3. Trading Flags — `core/trading_flags.py`

**Where:** After existing behavioral flags (~end of function)

Add futures-specific flags:

```python
# --- Futures flags ---
futures_breakdown = snapshot.get("futures_breakdown")
if futures_breakdown:
    futures_pnl = futures_breakdown.get("futures_pnl_usd", 0)
    futures_count = futures_breakdown.get("futures_trade_count", 0)

    # Large futures losses
    if futures_pnl < -5000 and futures_count >= 3:
        flags.append({
            "type": "futures_trading_losses",
            "severity": "warning",
            "message": f"Futures trading lost ${abs(futures_pnl):,.0f} across {futures_count} trades",
            "futures_pnl_usd": futures_pnl,
            "futures_trade_count": futures_count,
        })

    # Futures dominate P&L (>60% of total absolute P&L)
    equity_pnl = futures_breakdown.get("equity_pnl_usd", 0)
    total_abs_pnl = abs(futures_pnl) + abs(equity_pnl)
    if total_abs_pnl > 0 and abs(futures_pnl) / total_abs_pnl > 0.6:
        flags.append({
            "type": "futures_pnl_dominant",
            "severity": "info",
            "message": f"Futures account for {abs(futures_pnl)/total_abs_pnl*100:.0f}% of total trading P&L",
            "futures_pnl_pct": round(abs(futures_pnl) / total_abs_pnl * 100, 1),
        })
```

### 4. Realized Performance Metadata — `core/realized_performance_analysis.py`

**Already done.** All 5 futures metadata fields are already populated in the cash replay function `_replay_cash_series()` (lines 1606-1722):

- `futures_txn_count_replayed` — counted via `_futures_count` variable and accumulated into `replay_diagnostics` (line 1706)
- `futures_fee_cash_impact_usd` — summed from fee impact of futures trades (lines 1608, 1627, 1633, 1713)
- `futures_notional_suppressed_usd` — accumulated from `abs(price * quantity * fx)` for futures trades (line 1624, 1709)
- `futures_unknown_action_count` — counted for non-BUY/SELL/SHORT/COVER futures events (line 1629, 1717)
- `futures_missing_fx_count` — counted when FX fallback used for futures (line 1618, 1720)

These flow through `replay_diagnostics` → `RealizedMetadata` at lines 4519-4586. **No changes needed in this section.**

### 5. Pass instrument_type Through IBKR Flex Normalizer — `providers/normalizers/ibkr_flex.py`

Verify that `instrument_type` and `contract_identity` are preserved in the FIFO transaction dict built by the normalizer. Current code at lines 130-149 already passes these through — just confirm and add `multiplier` as a top-level convenience field:

```python
fifo_transactions.append({
    ...
    "instrument_type": txn.get("instrument_type", "equity"),
    "contract_identity": txn.get("contract_identity"),
    "is_futures": bool(txn.get("is_futures")),
    "multiplier": float((txn.get("contract_identity") or {}).get("multiplier", 1.0) or 1.0),  # NEW convenience
})
```

### 6. FIFOMatcher Transaction Threading — `trading_analysis/fifo_matcher.py`

**Where:** `process_transactions()` (line 373 loop), `_process_entry()` (line 486), `_process_exit()` (line 514), `_create_incomplete_trade()` (line 662)

Thread `instrument_type`, `multiplier`, and `contract_identity` from the `txn` dict through to OpenLot/ClosedTrade/IncompleteTrade creation.

**Step 1:** In `process_transactions()`, extract metadata from `txn` at the top of the loop (line 374):
```python
txn_meta = {
    "instrument_type": txn.get("instrument_type", "equity"),
    "contract_identity": txn.get("contract_identity"),
}
```

Pass `txn_meta` as a new parameter to every call to `_process_entry()`, `_process_exit()`, and `_create_incomplete_trade()`. There are 12 call sites in `process_transactions()`: `_process_entry` ×5 (lines 410, 413, 446, 454, 466), `_process_exit` ×6 (lines 406, 430, 433, 441, 459, 473), `_create_incomplete_trade` ×1 (line 451).

**Step 2:** Update `_process_entry()` signature to accept `txn_meta: dict`:
```python
def _process_entry(self, lot_key, symbol, currency, direction, date, quantity, price, fee, source, transaction_id, txn_meta=None):
    meta = txn_meta or {}
    lot = OpenLot(
        ...,
        direction=direction,
        # NEW:
        instrument_type=meta.get("instrument_type", "equity"),
        multiplier=float((meta.get("contract_identity") or {}).get("multiplier", 1.0) or 1.0),
        contract_quantity=_contract_qty(quantity, meta),
    )
```

**Step 3:** Update `_process_exit()` signature to accept `txn_meta: dict`. ClosedTrade inherits metadata from the OpenLot (entry side), not the exit transaction:
```python
# In _process_exit(), when creating ClosedTrade (lines 545, 577):
closed_trade = ClosedTrade(
    ...,
    entry_transaction_id=oldest_lot.transaction_id,
    exit_transaction_id=transaction_id,
    # NEW: inherit from lot (entry side)
    instrument_type=oldest_lot.instrument_type,
    multiplier=oldest_lot.multiplier,
    contract_quantity=_contract_qty(closed_qty, {"instrument_type": oldest_lot.instrument_type, "contract_identity": {"multiplier": oldest_lot.multiplier}}),
)
```

For the inline `IncompleteTrade` at line 601 (exit with no matching lots):
```python
incomplete = IncompleteTrade(
    ...,
    direction=direction,
    # NEW:
    instrument_type=(txn_meta or {}).get("instrument_type", "equity"),
    multiplier=float(((txn_meta or {}).get("contract_identity") or {}).get("multiplier", 1.0) or 1.0),
    contract_quantity=_contract_qty(quantity_to_close, txn_meta or {}),
)
```

**Step 4:** Update `_create_incomplete_trade()` similarly.

**Helper function** at module level:
```python
def _contract_qty(qty: float, meta: dict) -> Optional[float]:
    """Compute original contract count from pre-multiplied quantity."""
    if meta.get("instrument_type") != "futures":
        return None
    multiplier = float((meta.get("contract_identity") or {}).get("multiplier", 1.0) or 1.0)
    if multiplier > 1:
        return qty / multiplier
    return None
```

## Files Changed

| File | Change | Section |
|------|--------|---------|
| `trading_analysis/fifo_matcher.py` | Add `instrument_type`, `multiplier`, `contract_quantity` to OpenLot/ClosedTrade/IncompleteTrade; add `txn_meta` param to `_process_entry`/`_process_exit`/`_create_incomplete_trade`; add `_contract_qty()` helper | 1, 6 |
| `trading_analysis/models.py` | Add `instrument_type`, `multiplier`, `contract_quantity` to `TradeResult`; add `futures_breakdown` to agent snapshot; enrich top winners/losers | 2a, 2c |
| `trading_analysis/analyzer.py` | Thread `instrument_type`/`multiplier`/`contract_quantity` from `ClosedTrade` → `TradeResult` in `_analyze_trades_fifo()` | 2b |
| `core/trading_flags.py` | Add `futures_trading_losses` and `futures_pnl_dominant` flags | 3 |
| `core/realized_performance_analysis.py` | **No changes needed** — futures metadata already populated in cash replay | 4 |
| `providers/normalizers/ibkr_flex.py` | Add top-level `multiplier` convenience field to FIFO transaction dict | 5 |

## Tests

1. **ClosedTrade with futures metadata** — Construct ClosedTrade with `instrument_type="futures"`, `multiplier=50`, `contract_quantity=10`, verify P&L unchanged, verify new fields present
2. **OpenLot with futures metadata** — Same pattern
3. **_contract_qty helper** — `_contract_qty(500, {"instrument_type": "futures", "contract_identity": {"multiplier": 50}})` → 10.0; equity → None
4. **TradeResult with futures metadata** — Construct TradeResult with `instrument_type="futures"`, `multiplier=50`, `contract_quantity=10`, verify fields present and defaults correct for equities
5. **Agent snapshot futures_breakdown** — Mock FullAnalysisResult with mix of equity + futures `TradeResult` objects (not ClosedTrade), verify breakdown in snapshot
6. **Trading flags** — Futures losses >$5k → warning; futures dominant >60% → info; no futures → no flags
7. **End-to-end FIFO** — FIFO match a sequence with ES futures trades (pre-multiplied qty), verify ClosedTrade has correct `contract_quantity` and `instrument_type`
8. **End-to-end analyzer** — Run `_analyze_trades_fifo()` with futures transactions, verify `TradeResult` objects have correct `instrument_type`/`multiplier`/`contract_quantity` threaded from `ClosedTrade`
9. **Existing tests pass** — No P&L regression since math is unchanged

## Design Decisions

1. **No P&L math changes** — IBKR Flex already pre-multiplies quantity. The FIFO formula `(exit - entry) × qty` produces correct dollar P&L. Changing this would double-count.
2. **`contract_quantity` is display-only** — Computed as `qty / multiplier` for futures, `None` for equities. Used in agent snapshots and trade display, not in P&L math.
3. **Only IBKR normalizer updated** — Plaid, SnapTrade, and Schwab don't support futures trading. No changes needed.
4. **Futures metadata fields already exist** — `RealizedMetadata` has 6 futures fields (lines 144-149). We populate the 2 most useful ones; others filled as edge cases arise.
5. **Roll tracking deferred to Phase 6** — Requires contract month awareness (ES Z2024 vs ESH2025). Not critical for P&L attribution.
6. **Hypothetical performance needs no changes** — `get_returns_dataframe()` already handles futures via pricing chain (Phase 2). `compute_performance_metrics()` is instrument-agnostic.
