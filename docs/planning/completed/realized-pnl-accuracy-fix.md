# Realized Performance Accuracy Fix

Status: Completed

## Context

The realized performance pipeline has two output tracks that serve different purposes:

1. **Portfolio Returns (NAV track)**: Modified Dietz returns using market prices at each month-end, adjusted for external cash flows. This is the primary measure of portfolio performance over time.
2. **Lot-based P&L**: Realized + unrealized dollar P&L derived from FIFO cost lots. This tells you how much money you've made/lost.

Both tracks are distorted by three problems:

- **B-001 (Returns)**: Synthetic positions are placed at the global inception date (2022-08-18) instead of when the position was actually acquired. This puts positions in the NAV timeline years too early, attributing returns from periods when the stock wasn't held.
- **B-001/B-002 (P&L)**: Synthetic lots use an FMP price from 2022 as cost basis, unrelated to what was actually paid. The broker already reports total cost basis — we should use it.
- **B-009/B-010/B-011 (Both)**: SnapTrade SELLs without prior BUYs are inferred as SHORT entries, creating ~$20k of phantom short exposure in a long-only portfolio.

**Goal**: Reasonably accurate returns and P&L given limited transaction windows. When data is missing, be conservative.

---

## Fix 1: Per-Symbol Inception Date (Returns accuracy — B-001)

**Problem**: All synthetic positions enter the NAV at the global inception date (earliest txn across ALL symbols — 2022-08-18). STWD bought in Jan 2025 appears in the NAV from 2022, polluting 2.5 years of returns.

**Fix**: Use the earliest known transaction date *for that specific symbol* as the synthetic entry date. Fall back to global inception only for symbols with zero transaction history.

**File**: `core/realized_performance_analysis.py` — `build_position_timeline()` (~line 248)

```python
# Before the synthetic loop, build per-symbol earliest date map:
earliest_txn_by_symbol = {}
for txn in fifo_transactions:
    sym = txn.get("symbol", "").strip()
    dt = _to_datetime(txn.get("date"))
    if sym and dt:
        if sym not in earliest_txn_by_symbol or dt < earliest_txn_by_symbol[sym]:
            earliest_txn_by_symbol[sym] = dt

# In the synthetic loop (line 248), replace inception_date with:
symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
```

**Keying**: `earliest_txn_by_symbol` is keyed by symbol only (not symbol+direction). In the rare case where a symbol has both long and short history, the earliest date across both directions is used — this is conservative and correct for NAV placement.

**Timestamp safety**: Place synthetic entry at `symbol_inception - timedelta(seconds=1)` to avoid same-timestamp ordering conflicts when the first transaction for a symbol is a SELL (the synthetic BUY must come before it in the timeline).

**Why this works for returns**: The synthetic cash event uses market price at the entry date (FMP lookup). When the date matches reality, the flow matches the NAV, and there's no artificial gain/loss at entry. Subsequent months reflect actual market performance from the correct start date.

**Impact**: STWD enters NAV at 2025-01-30, CBL at 2025-02-13, AT.L at 2025-02-24, etc.

---

## Fix 2: Back-Solve Synthetic Cost for Realized P&L (B-001, B-002)

**Problem**: Synthetic FIFO lots get an FMP price from the inception date as their cost basis. This has no relation to what was actually paid, distorting the realized P&L track.

**Core insight**: The broker reports total `cost_basis` for each current position. Combined with known transaction costs from the FIFO window, we can derive the correct cost for missing pre-window shares.

**Scope**: This fix applies to **current positions only** (positions still held in the broker). Fully exited positions with no buy history are unknowable — those remain incomplete trades.

### Two-pass FIFO approach

The back-solved cost must reach the FIFO matcher as pre-seeded `OpenLot` entries. But `process_transactions()` calls `reset()` first, wiping any pre-seeded state. Solution: two-pass FIFO with `initial_open_lots` support.

**Pass 1**: Run FIFO normally to get observed open lots (what's already matched from in-window transactions).

**Compute seeded lots**: For each current position with missing openings, use observed open lots to isolate the pre-window cost:

```
pre_window_cost = broker_cost_basis - observed_open_lot_cost
pre_window_shares = current_shares - observed_open_lot_shares
seed_price = pre_window_cost / pre_window_shares
```

Seed quantity = `current_shares + in_window_exits - in_window_openings` (covers both currently-held AND sold pre-window shares, so in-window SELLs can match against them).

**Pass 2**: Re-run FIFO with seeded lots injected via `initial_open_lots` parameter. Seeded lots are dated at `earliest_symbol_txn - 1 second` so FIFO processes them first.

### Why two passes?

When there are both pre-window AND in-window buys for the same symbol, we need to separate their costs:

**Example** (partial-history):
- Before window: bought 200 @ unknown cost
- In window: bought 50 @ $20, sold 100 @ $30
- Current: 150 shares, broker cost_basis = $650

Pass 1 observed open lots: 50 × $20 = $1,000 cost (but only 50 shares remaining after SELL matched 100)
- Actually: SELL of 100 matches against whatever open lots exist. Need pass 1 to determine remaining observed cost.
- Pre-window cost = $650 - observed_remaining_cost
- Seed price = pre_window_cost / pre_window_remaining_shares

**Example** (zero-history, simpler):
- No transactions at all, current: 100 shares, broker cost_basis = $500
- No observed lots → seed_price = $500 / 100 = $5/share

### FIFOMatcher changes

**File**: `trading_analysis/fifo_matcher.py`

Add `initial_open_lots` support:

```python
def reset(self, initial_open_lots=None):
    self.open_lots = defaultdict(list)
    self.closed_trades = []
    self.incomplete_trades = []
    self.inferred_shorts = set()
    if initial_open_lots:
        for key, lots in initial_open_lots.items():
            for lot in lots:
                self.open_lots[key].append(lot)  # clone if needed
            self.open_lots[key].sort(key=lambda x: x.entry_date)

def process_transactions(self, transactions, ..., initial_open_lots=None):
    self.reset(initial_open_lots=initial_open_lots)
    ...
```

### Caller change in `analyze_realized_performance()`

```python
# Pass 1: observed lots only
probe_result = FIFOMatcher(no_infer_symbols=no_infer_symbols
    ).process_transactions(fifo_transactions)

# Compute seeded lots from broker cost basis
seeded_lots, seed_warnings = _build_seed_open_lots(
    fifo_transactions, current_positions,
    observed_open_lots=probe_result.open_lots,
    inception_date=inception_date,
)
warnings.extend(seed_warnings)

# Pass 2: with seeded lots (or reuse pass 1 if nothing to seed)
if seeded_lots:
    fifo_result = FIFOMatcher(no_infer_symbols=no_infer_symbols
        ).process_transactions(fifo_transactions, initial_open_lots=seeded_lots)
else:
    fifo_result = probe_result
```

### Guards

- Skip seeding if broker `cost_basis` is None or ≤ 0
- Skip if `pre_window_cost ≤ 0` (broker cost < observed lot cost — data inconsistency)
- Skip if `pre_window_remaining_shares ≤ 0` (all pre-window shares sold in-window — can't determine cost from broker data; leave as incomplete trades)
- **Currency alignment**: If `cost_basis_is_usd=True` but position currency isn't USD, convert observed lot cost to USD (via `fx_cache`) before subtracting. Otherwise units don't match and seed price is wrong.
- **Scope to LONG only**: Only seed lots for long positions. Short positions are rare and handled by delta-gap inference (Fix 3). Short seeding can be added as follow-up if needed.
- **Fee handling**: Use `remaining_quantity * entry_price + remaining_entry_fee` for observed lot cost (not original fees — partial closes reduce remaining fees).
- **Clone seeded lots**: When injecting into pass 2, clone `OpenLot` objects to avoid mutation coupling between passes.
- **Cost assumption**: Pre-window shares (both currently held and sold in-window) are assumed to share the same unit cost. This is an approximation — the broker's average cost applies to surviving shares, not necessarily to shares sold in-window. This is acceptable: the alternative (unknowable) is worse.
- Log warnings for all skipped seeds

### Cases

| Case | Seed price | Example |
|------|-----------|---------|
| **Partial-history** | `(broker_cost - observed_lot_cost) / pre_window_remaining_shares` | STWD, CBL, MSCI |
| **Zero-history** | `broker_cost / current_shares` | NVDA, TKO, V |
| **No broker cost** | Fall back to FMP price lookup. Flag low-confidence. | CPPMF |

### Unrealized P&L

Unrealized P&L uses broker data directly — no synthetics or FIFO lots needed:

```
broker_unrealized_pnl = current_portfolio_value - total_cost_basis_usd
```

Both values are already computed in `analyze_realized_performance()` (lines 1250-1267). This is the primary unrealized P&L number. The FIFO-based `unrealized_pnl` (from `_compute_unrealized_pnl_usd()`) remains as a secondary "observed lots only" metric.

**Note**: The NAV track still uses market prices from FMP for cash flow computation (returns) — separate from both realized and unrealized P&L.

---

## Fix 3: Delta-Based Short Inference (B-009/B-010/B-011)

**Problem**: `FIFOMatcher` eagerly infers SHORT when it sees a SnapTrade SELL without prior BUY. This is correct for real shorts, but creates phantom short exposure when the BUY is simply outside the transaction window. The current guard (`config/not_shorts.txt`) uses SnapTrade transaction IDs which drift over time, causing curated exclusions to silently fail.

**Key constraint**: None of the three sources (IBKR Flex, SnapTrade, Plaid) provide cost basis on SELL transactions. For a fully-exited position (SELL with no BUY, not in current holdings), P&L is unknowable regardless of whether we call it a short or an incomplete trade.

### Approach: Delta-gap analysis

Pre-compute a per-symbol "gap" before running FIFO:

```
visible_net_delta = total_BUYs - total_SELLs  (from transaction window)
gap = current_holdings - visible_net_delta
```

- **gap = 0** → visible transactions fully explain the position. SELLs without prior BUYs are likely real shorts (the round-trip is self-contained within the window).
- **gap > 0** → there are missing buys from before the window. SELLs without prior BUYs are likely long exits, not shorts. Don't infer.

**Assumption**: Delta-gap is computed using all transaction sources. If source filtering is used, the gap calculation should also filter positions accordingly (or fall back to `infer_shorts=False`).

### Evidence (edge cases verified):

| Scenario | Delta | Holdings | Gap | Inference |
|----------|-------|----------|-----|-----------|
| Short round-trip: SELL 100, BUY 100 | 0 | 0 | 0 | Short ✓ |
| Long exit, missing buy: SELL 100 | -100 | 0 | +100 | Incomplete ✓ |
| Partial history: SELL 100, BUY 50 | -50 | +50 | +100 | Incomplete ✓ |
| Open short: SELL 100 | -100 | -100 | 0 | Short ✓ |
| Short→cover→go long: SELL 100, BUY 150 | +50 | +50 | 0 | Short ✓ |
| Mixed (rare): long exit + short same symbol | -100 | 0 | +100 | Incomplete (conservative) |

The mixed case is the only imprecision — a real short on the same symbol as a long exit with missing history gets treated as incomplete. This is rare and fails conservatively.

### Implementation

**File**: `trading_analysis/fifo_matcher.py`

1. Replace `_should_infer_short()` — remove ID-based check, add `no_infer_symbols`:

```python
def __init__(self, ..., no_infer_symbols: Optional[Set[str]] = None):
    ...
    self.no_infer_symbols = no_infer_symbols or set()

def _should_infer_short(self, symbol, source, txn_id):
    if not self.infer_shorts:
        return False
    if source != 'snaptrade':
        return False
    if txn_id is None:
        return False
    # Delta-gap check: don't infer shorts for symbols with missing buy history
    if symbol in self.no_infer_symbols:
        return False
    return True
```

2. Remove `config/not_shorts.txt` and all related code entirely:
   - Delete `config/not_shorts.txt` file
   - Remove `load_not_shorts_list()` function in `fifo_matcher.py`
   - Remove `self.not_shorts` set and all references
   - Remove `not_shorts_config_path` constructor parameter

**Caller change** in `analyze_realized_performance()`:

```python
# Pre-compute delta gap per symbol
visible_delta = defaultdict(float)
for txn in fifo_transactions:
    sym = txn.get("symbol", "").strip()
    qty = abs(float(txn.get("quantity", 0)))
    txn_type = txn.get("type", "").upper()
    if txn_type in ("BUY", "COVER"):
        visible_delta[sym] += qty
    elif txn_type in ("SELL", "SHORT"):
        visible_delta[sym] -= qty

no_infer_symbols = set()
for sym, delta in visible_delta.items():
    holdings = current_positions.get(sym, {}).get("shares", 0)
    gap = holdings - delta
    if gap > 0.01:  # missing buys → don't infer shorts
        no_infer_symbols.add(sym)

fifo_result = FIFOMatcher(
    no_infer_symbols=no_infer_symbols
).process_transactions(fifo_transactions)
```

**Rationale**: The delta-gap approach is data-driven and self-maintaining — no manual curation of transaction IDs that drift over time. It correctly handles real shorts (self-contained round-trips) while filtering out false positives (long exits with missing history).

**Trade-off**: Fully covered historical shorts where there's ALSO missing long buy history on the same symbol will be treated as incomplete. This is acceptable — it's a rare edge case, fails conservatively, and the P&L is unknowable anyway.

**Impact** (from live comparison):
- Inferred shorts: 15 → 0 (no current short positions, all have gaps)
- Unrealized P&L: -$24k → -$2k
- Incomplete trades: 18 → ~34 (honest gaps, not fabricated shorts)

---

## Verification

1. **Unit tests**:
   - `tests/core/test_realized_performance_analysis.py`:
     - Per-symbol inception: synthetic entry uses symbol's earliest txn date, not global
     - Zero-history symbol falls back to global inception
     - Back-solved cost basis: injected lot has correct price
     - Zero-history cost: `price = broker_cost / shares`
   - `tests/trading_analysis/test_fifo_matcher.py`:
     - Delta gap=0 (short round-trip): SELL→BUY→no holdings → inferred as short
     - Delta gap>0 (missing buys): SELL→no holdings → incomplete trade, not short
     - Symbol in `no_infer_symbols` → never inferred as short
     - `not_shorts.txt` code fully removed, no regressions

2. **Diagnostic script**: `python3 tests/diagnostics/diagnose_realized.py` before/after:
   - Synthetic position dates (per-symbol, not all 2022-08-18)
   - Inferred shorts count → 0
   - Reconciliation gap narrows

3. **Live MCP**: `get_performance(mode="realized")`:
   - `inferred_shorts` = 0
   - Unrealized P&L reasonable (not -$24k)
   - `reconciliation_gap_usd` smaller

## Unpriceable Symbols (B-005)

Symbols that FMP cannot price (options, FX pairs, treasuries) still flow through normal classification and FIFO matching. They are correctly categorized as long/short and lot-matched, but excluded from P&L and returns since there is no price data. These are captured as a separate data gap list for future resolution (e.g. adding option pricing, treasury pricing sources, or manual price overrides).

No code change needed — the existing pipeline already values these at $0 in the NAV. The diagnostic script (`tests/diagnostics/diagnose_realized.py`) already surfaces them.

---

## Future Work: Incomplete Trade Backfill

Incomplete trades (exits without matching entries) represent real P&L that occurred during the analysis period but is currently unmeasurable. To close this gap:

1. **Brokerage query**: Investigate whether SnapTrade positions API or IBKR account statements can provide historical cost basis for closed positions (not just current holdings).
2. **Manual backfill**: The existing `incomplete_trades_backfill.json` pipeline supports `manual_entry_price` and `manual_entry_date`. Export current incomplete trades list, cross-reference with broker statements, and populate.
3. **Entry dates for returns**: If entry dates can be obtained (from broker statements or manual input), incomplete trades can be placed correctly in the NAV timeline — improving return accuracy in addition to P&L.

This is deferred work — the current fixes give us a reasonably accurate picture by excluding unknowable trades rather than fabricating data for them.

---

## Order of Implementation

1. Fix 3 (delta-gap short inference) — implement first, changes incomplete trade counts which affect Fix 1/2
2. Fix 1 (per-symbol inception date) — returns accuracy
3. Fix 2 (inject back-solved lots into FIFO) — realized P&L accuracy

Fix 3 should go first since it changes the FIFO output (incomplete trades, inferred shorts) that feeds into the other fixes. Fixes 1 and 2 can then be done in either order.
