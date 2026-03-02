# Futures Monthly Contracts, Term Structure & Roll Execution

## Context

Phases 1–5 built full futures support for **continuous contracts** — pricing, portfolio integration, risk, trading analysis. But futures are inherently date-specific: you trade ESM2026 (March) or ESU2026 (June), not just "ES". The system currently can't:
- Resolve a specific contract month (only `ContFuture` continuous)
- Show the futures curve / term structure (prices across months)
- Execute calendar rolls as atomic combo orders (sell front + buy back)

This plan adds all three as a layered feature stack. Monthly resolution is the foundation; curve and roll build on it independently.

## Architecture

```
Phase 1: Monthly Contract Resolution (ibkr/ layer)
    ↓
Phase 2: Futures Curve MCP Tool ──── Phase 3: Roll Execution
  (informational, read-only)          (trading, writes)
```

Phases 2 and 3 are independent of each other after Phase 1.

---

## Phase 1: Monthly Contract Resolution

**Goal:** Let callers resolve specific contract months (e.g., ESM2026) and discover what months are available.

### 1a. `ibkr/contracts.py` — Add `contract_month` param

Extend `resolve_futures_contract()` (line 53):

```python
def resolve_futures_contract(
    symbol: str,
    contract_month: str | None = None,
) -> Contract:
    """Resolve a futures root symbol into an IBKR contract.

    When contract_month is None, returns ContFuture (continuous).
    When contract_month is set (YYYYMM or YYYYMMDD), returns
    a specific monthly Future contract.
    """
    from ib_async import ContFuture, Future

    sym = str(symbol or "").strip().upper()
    exchange, currency = _futures_exchange_meta(sym)

    if contract_month is None:
        return ContFuture(symbol=sym, exchange=exchange, currency=currency)

    # Validate format: 6 digits (YYYYMM) or 8 digits (YYYYMMDD)
    cm = str(contract_month).strip()
    if not re.match(r"^\d{6}(\d{2})?$", cm):
        raise IBKRContractError(
            f"Invalid contract_month '{contract_month}' — expected YYYYMM or YYYYMMDD"
        )
    return Future(symbol=sym, lastTradeDateOrContractMonth=cm,
                  exchange=exchange, currency=currency)
```

**Backward-compatible:** All existing callers pass no `contract_month`, so they still get `ContFuture`.

Update `resolve_contract()` (line 189) to thread through:
```python
if normalized == "futures":
    month = (contract_identity or {}).get("contract_month")
    return resolve_futures_contract(symbol, contract_month=month)
```

### 1b. `ibkr/metadata.py` — Add `fetch_futures_months()`

New function to discover available contract months for a root symbol:

```python
def fetch_futures_months(
    ib,
    symbol: str,
) -> list[dict[str, Any]]:
    """Discover available contract months for a futures root symbol.

    Returns list of dicts sorted by last_trade_date ascending, with keys:
    con_id, symbol, exchange, currency, last_trade_date, multiplier, trading_class
    """
```

Implementation:
- Get exchange/currency from `_futures_exchange_meta(symbol)` (reuse existing YAML lookup)
- Build `Future(symbol=sym, exchange=exchange, currency=currency)` — bare Future without month → IBKR returns ALL monthly contracts via `reqContractDetails()`
- Normalize each via existing `_normalize_contract_detail()` (already captures `last_trade_date` from `lastTradeDateOrContractMonth`, line 70-72)
- Filter out expired contracts (`last_trade_date < today`)
- Sort by `last_trade_date` ascending

**Key insight:** `_build_contract()` (line 33-38) already handles bare `Future` when exchange is explicit. We use `_futures_exchange_meta()` to get the correct exchange from YAML, avoiding the SMART routing issue.

### 1c. `ibkr/client.py` — Add `get_futures_months()` method

```python
def get_futures_months(self, symbol: str) -> list[dict[str, Any]]:
    """Discover available contract months for a futures root."""
```

Follows existing pattern: manages connection + lock, delegates to `fetch_futures_months()`.

### 1d. `ibkr/compat.py` — Add public boundary

```python
def get_futures_months(symbol: str) -> list[dict[str, Any]]:
    """Discover available contract months for a futures root symbol."""
```

Add to `__all__`.

### Phase 1 Tests

- `resolve_futures_contract(symbol)` → still returns ContFuture (no change)
- `resolve_futures_contract(symbol, contract_month="202603")` → returns Future with lastTradeDateOrContractMonth
- `resolve_futures_contract(symbol, contract_month="abc")` → raises IBKRContractError
- `resolve_contract("ES", "futures", {"contract_month": "202603"})` → threads through
- `fetch_futures_months()` with mock IB returning 4 contract details → sorted, expired filtered

---

## Phase 2: Futures Curve (Term Structure) MCP Tool

**Goal:** New `get_futures_curve(symbol)` MCP tool showing prices across all active months — contango/backwardation, calendar spreads, annualized basis.

**IBKR-only for curve data** — FMP has continuous contracts only, no per-month pricing.

### 2a. `ibkr/market_data.py` — Add `fetch_futures_curve_snapshot()`

```python
def fetch_futures_curve_snapshot(
    self,
    symbol: str,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Snapshot last/bid/ask/volume for all active monthly contracts.

    Returns list of dicts with:
    con_id, last_trade_date, last, bid, ask, volume, open_interest
    sorted by last_trade_date ascending.
    """
```

Implementation:
- Call `fetch_futures_months()` to discover available months (via metadata.py)
- Build `Contract(conId=month["con_id"])` for each month
- Use existing `fetch_snapshot()` (line 500) to get bid/ask/last/volume
- Merge snapshot data with month metadata
- **Filter out months with no price data** — `fetch_snapshot()` can return None/NaN for illiquid back months; exclude these from spread/basis calculations
- Return merged list sorted by `last_trade_date` (only months with valid prices)

This reuses the existing `fetch_snapshot()` method (already supports batch contract snapshots with timeout).

### 2b. `ibkr/client.py` + `ibkr/compat.py` — Expose curve snapshot

Add `get_futures_curve_snapshot(symbol)` method to client facade and compat boundary.

### 2c. New: `core/futures_curve_flags.py` — Interpretive flags

Following `core/chain_analysis_flags.py` pattern:

```python
def generate_futures_curve_flags(snapshot: dict) -> list[dict]:
```

Flags:
- `contango` (info) — curve is upward sloping (front < back)
- `backwardation` (info) — curve downward sloping (front > back)
- `steep_contango` (warning) — front-to-back annualized basis > 5%
- `near_expiry_front` (info) — front month expires within 5 trading days
- `low_liquidity_warning` (warning) — back months have very low volume
- `curve_fetched` (success) — standard completion

### 2d. New: `mcp_tools/futures_curve.py` — MCP tool

Following `mcp_tools/chain_analysis.py` three-layer pattern:

```python
@handle_mcp_errors
def get_futures_curve(
    symbol: str,
    format: Literal["full", "summary", "agent"] = "summary",
    output: Literal["inline", "file"] = "inline",
) -> dict:
    """Fetch futures term structure for a root symbol.

    Shows prices for all active contract months, calendar spreads,
    and contango/backwardation analysis.

    Args:
        symbol: Futures root symbol (e.g., "ES", "NQ", "GC", "CL")
        format: "summary" (default), "full", or "agent"
        output: "inline" (default) or "file" (save to logs/futures/)

    Examples:
        get_futures_curve(symbol="ES")
        get_futures_curve(symbol="GC", format="agent")
    """
```

Internal helpers:
- `_compute_term_structure(months_with_prices, contract_spec)` — calendar spreads, annualized basis, curve shape
- `_build_agent_response(summary, symbol, file_path)` — compose agent format
- `_save_curve_analysis(result, symbol)` — save to `logs/futures/curve_{symbol}_{timestamp}.json`

**Agent snapshot shape:**
```python
{
    "status": "success",
    "symbol": "ES",
    "verdict": "ES: 4 active months, contango, front 5800.25 (Mar 2026), +0.51% to Dec 2026",
    "curve_shape": "contango",  # or "backwardation" or "flat"
    "month_count": 4,
    "front_month": "202603",
    "front_price": 5800.25,
    "back_month": "202612",
    "back_price": 5830.00,
    "total_spread": 29.75,
    "total_spread_pct": 0.51,
    "nearest_spread": 15.50,
    "nearest_annualized_basis_pct": 1.07,
    "days_to_front_expiry": 18,
    "months": [
        {"month": "202603", "price": 5800.25, "volume": 12345, "days_to_expiry": 18},
        {"month": "202606", "price": 5815.75, "volume": 8900, "days_to_expiry": 109},
    ],
    "spreads": [
        {"front": "202603", "back": "202606", "spread": 15.50, "ann_basis_pct": 1.07},
    ],
}
```

### 2e. `mcp_server.py` — Register tool

Standard registration pattern, passing all params through.

### Phase 2 Tests

- Term structure computation: contango detected (ascending prices), backwardation (descending)
- Calendar spread math: spread = back - front, annualized basis = spread/front * 365/days * 100
- Flag generation: contango flag, steep_contango flag, near_expiry flag
- Agent format: snapshot + flags + file_path structure
- Edge cases: single month (no spreads), no data (error status)
- File output: saves to `logs/futures/` directory

---

## Phase 3: Roll Execution

**Goal:** Execute calendar rolls as atomic combo orders (sell front month + buy back month as a single BAG order).

**Dedicated tools** (not extending `preview_trade`/`execute_trade`) because:
- Roll involves two legs with fundamentally different contract construction (BAG with ComboLegs)
- Roll-specific validation (same root, front < back)
- Spread limit price semantics differ from absolute price

### 3a. `brokerage/ibkr/adapter.py` — Add `_build_roll_contract()` + `preview_roll()` + `place_roll()`

**Note:** `_build_roll_contract()` lives in the adapter (not `ibkr/contracts.py`) because it requires an `ib` session handle for `qualifyContracts()`. `contracts.py` is pure contract construction with no IB session dependency.

```python
def _build_roll_contract(
    self,
    ib,
    symbol: str,
    front_month: str,
    back_month: str,
    direction: Literal["long_roll", "short_roll"] = "long_roll",
) -> Contract:
    """Build a BAG combo contract for a calendar roll.

    long_roll (default): SELL front_month + BUY back_month
        (rolling a long position forward)
    short_roll: BUY front_month + SELL back_month
        (rolling a short position forward)

    Returns qualified BAG Contract ready for whatIfOrder/placeOrder.
    """
```

Implementation:
- Resolve front + back via `resolve_futures_contract(symbol, contract_month=front_month|back_month)` (from Phase 1)
- Qualify both contracts to get conIds via `ib.qualifyContracts()`
- Build `ComboLeg` objects based on direction:
  - `long_roll`: SELL front + BUY back (most common — rolling a long position)
  - `short_roll`: BUY front + SELL back (rolling a short position)
- Build `Contract(secType="BAG", symbol=symbol, exchange=exchange, currency=currency, comboLegs=[leg1, leg2])`
- Return the BAG contract

```python
def preview_roll(
    self,
    account_id: str,
    symbol: str,
    front_month: str,
    back_month: str,
    quantity: float,
    direction: str = "long_roll",
    order_type: str = "Market",
    limit_price: float | None = None,
    time_in_force: str = "Day",
) -> OrderPreview:
    """Preview a calendar roll as a BAG combo order."""
```

Implementation:
- Call `_build_roll_contract(ib, symbol, front_month, back_month, direction)` to get BAG contract
- Call `_build_order(side="BUY", quantity, order_type, ...)` — BUY the spread (IBKR convention: action on BAG is always BUY for the spread; direction of individual legs is set in ComboLeg)
- Call `ib.whatIfOrder(bag_contract, order)` — same API, works for combos
- Return `OrderPreview` with roll-specific fields in `broker_preview_data` (front_month, back_month, front_con_id, back_con_id, direction)

```python
def place_roll(
    self,
    account_id: str,
    order_params: dict[str, Any],
) -> OrderResult:
    """Execute a previously previewed calendar roll."""
```

Implementation:
- Re-qualify BAG contract from stored params
- Build order from stored params
- Call `ib.placeOrder(bag_contract, order)` — same API as single-leg

### 3c. `services/trade_execution_service.py` — Add roll support

```python
def preview_roll(self, account_id, symbol, front_month, back_month, quantity, direction, order_type, limit_price, time_in_force) -> TradePreviewResult:
def execute_roll(self, preview_id: str) -> TradeExecutionResult:
```

Follow existing `preview_order`/`execute_order` pattern:
- `preview_roll` resolves adapter, calls `adapter.preview_roll(... direction=direction ...)`, stores in `trade_previews` with `order_category="roll"` and `direction` in preview data
- `execute_roll` loads preview, verifies it's a roll, calls `adapter.place_roll()`

### 3d. New: `mcp_tools/futures_roll.py` — MCP tools

```python
@handle_mcp_errors
def preview_futures_roll(
    symbol: str,
    front_month: str,
    back_month: str,
    quantity: float,
    direction: Literal["long_roll", "short_roll"] = "long_roll",
    account_id: str | None = None,
    order_type: Literal["Market", "Limit"] = "Market",
    limit_price: float | None = None,
    time_in_force: Literal["Day", "GTC"] = "Day",
    user_email: str | None = None,
) -> dict:
    """Preview a futures calendar roll as a single atomic combo/spread order.

    Args:
        symbol: Futures root symbol (e.g., "ES", "NQ", "GC")
        front_month: Expiring month (YYYYMM, e.g., "202603")
        back_month: Target month (YYYYMM, e.g., "202606")
        quantity: Number of contracts to roll
        direction: "long_roll" (sell front, buy back — default) or
                   "short_roll" (buy front, sell back)
        order_type: "Market" or "Limit"
        limit_price: Max spread for Limit orders

    Returns: Preview with estimated spread, commission, margin impact, and preview_id.
    """

@handle_mcp_errors
def execute_futures_roll(preview_id: str, user_email: str | None = None) -> dict:
    """Execute a previously previewed futures roll by preview_id."""
```

Validation in `preview_futures_roll`:
- front_month < back_month (chronologically)
- Both valid YYYYMM format
- Symbol exists in `exchange_mappings.yaml` (only the 27 configured contracts are supported — this is by design; unknown symbols fail fast with a clear error from `_futures_exchange_meta()`)
- direction in `{"long_roll", "short_roll"}` (enforced by Literal type)
- quantity > 0

### 3e. `mcp_server.py` — Register tools

Register `preview_futures_roll` and `execute_futures_roll` with docstrings.

### Phase 3 Tests

- `_build_roll_contract()` long_roll: BAG contract has secType="BAG", two ComboLegs (SELL front, BUY back)
- `_build_roll_contract()` short_roll: ComboLegs reversed (BUY front, SELL back)
- `preview_roll()`: mock IB, verify whatIfOrder called with BAG contract, direction threaded
- `place_roll()`: mock IB, verify placeOrder called with BAG contract
- Validation: front_month >= back_month → error, bad format → error, unknown symbol → error
- Direction threading: direction flows MCP → service → adapter → `_build_roll_contract()`
- MCP layer: preview returns preview_id, execute uses it
- IBKR_READONLY gate: place_roll raises when readonly

---

## Files Changed Summary

| Phase | File | Change |
|-------|------|--------|
| 1 | `ibkr/contracts.py` | Add `contract_month` param to `resolve_futures_contract()`, update `resolve_contract()` |
| 1 | `ibkr/metadata.py` | Add `fetch_futures_months()` |
| 1 | `ibkr/client.py` | Add `get_futures_months()` facade method |
| 1 | `ibkr/compat.py` | Add `get_futures_months()` public boundary + `__all__` |
| 2 | `ibkr/market_data.py` | Add `fetch_futures_curve_snapshot()` |
| 2 | `ibkr/client.py` | Add `get_futures_curve_snapshot()` facade method |
| 2 | `ibkr/compat.py` | Add `get_futures_curve_snapshot()` + `__all__` |
| 2 | **NEW** `core/futures_curve_flags.py` | Flag generation for curve analysis |
| 2 | **NEW** `mcp_tools/futures_curve.py` | `get_futures_curve()` MCP tool |
| 2 | `mcp_server.py` | Register `get_futures_curve` |
| 3 | `brokerage/ibkr/adapter.py` | Add `_build_roll_contract()` + `preview_roll()` + `place_roll()` |
| 3 | `services/trade_execution_service.py` | Add `preview_roll()` + `execute_roll()` |
| 3 | **NEW** `mcp_tools/futures_roll.py` | `preview_futures_roll()` + `execute_futures_roll()` MCP tools |
| 3 | `mcp_server.py` | Register roll tools |

## Verification

### Phase 1
1. `python3 -m pytest tests/ -x -q` — all tests pass
2. Live: `IBKRClient().get_futures_months("ES")` → returns list of monthly contracts with con_ids

### Phase 2
1. `python3 -m pytest tests/ -x -q`
2. `/mcp` reconnect
3. `get_futures_curve(symbol="ES", format="agent")` → shows term structure with contango/backwardation

### Phase 3
1. `python3 -m pytest tests/ -x -q`
2. `/mcp` reconnect
3. `preview_futures_roll(symbol="ES", front_month="202603", back_month="202606", quantity=1)` → preview with spread + margin impact
