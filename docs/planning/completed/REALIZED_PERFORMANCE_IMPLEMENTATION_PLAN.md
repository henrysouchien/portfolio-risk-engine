# Realized Performance Implementation Plan

**Status:** COMPLETE
**Prerequisite:** Performance Metrics Engine Extraction (COMPLETE)
**Reference:** `REALIZED_PERFORMANCE_MCP_PLAN.md` (high-level goals)

---

## Context

Add a `mode="realized"` option to the existing `get_performance` MCP tool that computes actual portfolio performance from transaction history (Plaid + SnapTrade). Unlike `mode="hypothetical"` (which backtests current composition), this uses real transactions to build month-end portfolio snapshots and compute true time-weighted returns including both realized and unrealized gains.

**Key design decisions:**
1. **Integrated into existing tool** — `get_performance(mode="realized")` rather than a separate tool
2. **Cash-inclusive NAV** — NAV = positions_value + derived_cash_balance. Cash is tracked implicitly from trades (BUY/COVER decrease cash, SELL/SHORT/INCOME increase cash). External flows are detected when cash goes negative (capital injection required). This correctly handles both long and short positions, and avoids the invested-sleeve problem where short proceeds vanish from NAV.
3. **Synthetic starting positions** — for current holdings without matching buys, create synthetic entries priced at market. For FIFO incomplete trades, synthesize at/before the trade date (not globally at inception).

---

## Currency Data Flow

**Problem:** `NormalizedTrade` and `NormalizedIncome` have no `currency` field — currency is lost during normalization.

**Solution for trades:** Use `TradingAnalyzer.fifo_transactions` (List[Dict]) instead of `self.trades` (List[NormalizedTrade]) for position reconstruction. The `fifo_transactions` dicts preserve currency from raw API data:

```python
# Each fifo_transaction dict has:
{
    'symbol': str,
    'type': str,       # 'BUY', 'SELL', 'SHORT', 'COVER'
    'date': datetime,
    'quantity': float,
    'price': float,
    'fee': float,
    'currency': str,   # preserved from PlaidTransaction.iso_currency_code / SnapTradeActivity.currency
    'source': str,     # 'plaid' or 'snaptrade'
    'transaction_id': str,
}
```

**Solution for income:** Build a parallel `income_with_currency` list during our orchestrator by pairing each `NormalizedIncome` with the currency inferred from `fifo_transactions` for the same symbol. Fallback: look up currency from current positions or default to USD.

```python
# In analyze_realized_performance():
symbol_currency_map = {txn['symbol']: txn['currency'] for txn in fifo_transactions}
# Also populate from current positions for symbols with no transactions
for ticker, pos in current_positions.items():
    symbol_currency_map.setdefault(ticker, pos.get('currency', 'USD'))

income_with_currency = [
    {'symbol': inc.symbol, 'date': inc.date, 'amount': inc.amount,
     'income_type': inc.income_type, 'currency': symbol_currency_map.get(inc.symbol, 'USD')}
    for inc in analyzer.income_events
]
```

Currency is also available on FIFO output objects:
- `IncompleteTrade.currency` — for synthetic position identification
- `ClosedTrade.currency` — for realized P&L by currency
- `OpenLot.currency` — for current open positions

We do **NOT** modify `NormalizedTrade` or `NormalizedIncome` (avoid breaking existing consumers).

---

## Algorithm: Monthly Return Series from Transactions

### Step 1: Gather Data
- Current positions from `PositionService.get_all_positions()` (includes currency, cost_basis)
- All transactions via `TradingAnalyzer` (Plaid + SnapTrade)
  - Use `analyzer.fifo_transactions` (dicts with currency) for position reconstruction
  - Use `analyzer.income_events` + symbol→currency map for income (see Currency Data Flow)
  - Run FIFO matching via `FIFOMatcher().process_transactions(fifo_transactions)` to get `FIFOMatcherResult`
- Determine inception date = earliest transaction date from `fifo_transactions`
- **Fallback if no transactions but positions exist**: inception_date = 12 months ago, all positions synthetic, data_coverage = 0%

### Step 2: Build Transaction Timeline
- Use `analyzer.fifo_transactions` directly (already normalized with currency)
- Extract BUY/SELL/SHORT/COVER trades with dates, quantities, prices, fees, currency
- Build `income_with_currency` list (see Currency Data Flow section)
- No need to call `_normalize_data()` separately — `TradingAnalyzer.__init__()` calls it automatically

### Step 3: Identify Synthetic Positions
Two sources of incomplete history requiring synthesis:

1. **Current holdings with no matching transactions**: ticker in current positions but no BUY/SHORT in `fifo_transactions`
   - Date = **inception date** (earliest overall transaction)
   - Quantity = current shares + any net sells in history

2. **FIFO incomplete trades**: sells/covers without prior buys — from `FIFOMatcherResult.incomplete_trades`
   - Date = **just before the incomplete trade's sell/cover date** (not inception). This avoids fabricating early exposure that never existed.
   - Quantity = incomplete trade's quantity
   - Use `IncompleteTrade.direction` to determine if this is a long or short synthetic entry

For all synthetic positions:
- Price = market close at synthetic date via `fetch_monthly_close()`
- Currency = from `IncompleteTrade.currency` or current position data
- Flag as `(ticker, currency, direction)` in synthetic_positions list for data_coverage tracking

### Step 4: Reconstruct Month-End Positions
Walk forward from inception, applying all transactions (real + synthetic) chronologically.

Position key: `(ticker, currency, direction)` — matches FIFO's internal keying to preserve direction awareness.

- BUY → add shares to `(ticker, currency, LONG)` position
- SELL → remove shares from `(ticker, currency, LONG)` position
- SHORT → add shares to `(ticker, currency, SHORT)` position (stored as positive quantity; valued as negative in Step 5)
- COVER → remove shares from `(ticker, currency, SHORT)` position
- At each month-end boundary, snapshot all position quantities by `(ticker, currency, direction)`

### Step 5: Price Month-End Snapshots
For each unique ticker, fetch **one** monthly close series spanning inception→end:
```python
prices[ticker] = fetch_monthly_close(ticker, inception_date, end_date, fmp_ticker_map)
```

For each unique non-USD currency, fetch **one** monthly FX series:
```python
fx_series[currency] = get_monthly_fx_series(currency, inception_date, end_date)
```

Then for each month-end snapshot:
- Look up price from pre-fetched price series
- For non-USD positions, look up FX rate from pre-fetched FX series (same month-end)
- For LONG positions: `value_usd = +shares × price × fx_rate`
- For SHORT positions: `value_usd = -shares × price × fx_rate` (negative exposure)
- Compute `cash_balance` by replaying all events (trades + income) up to this month-end (see Step 5b)
- Portfolio NAV = sum of all position values in USD + cash_balance

### Step 5b: Derive Cash Balance and Detect External Flows
Maintain a running `cash` balance starting at 0. Process **all events** (trades + income) in a single unified stream sorted chronologically:

```python
cash = 0.0
external_flows = []  # (date, amount) pairs

# Build unified event stream: trades + income, sorted by date
events = []
for txn in fifo_transactions:
    events.append({'date': txn['date'], 'event_type': txn['type'],
                   'price': txn['price'], 'quantity': txn['quantity'],
                   'fee': txn['fee'], 'currency': txn['currency']})
for inc in income_with_currency:
    events.append({'date': inc['date'], 'event_type': 'INCOME',
                   'amount': inc['amount'], 'currency': inc['currency']})

# Sort by date, then by type priority: SELL/SHORT first (cash inflows),
# then INCOME, then BUY/COVER last (cash outflows).
# This minimizes false injection detection on same-day rebalancing.
TYPE_ORDER = {'SELL': 0, 'SHORT': 1, 'INCOME': 2, 'BUY': 3, 'COVER': 4}
events.sort(key=lambda e: (e['date'], TYPE_ORDER.get(e['event_type'], 5)))

for event in events:
    fx = fx_rate_at(event['currency'], event['date'])

    if event['event_type'] == 'BUY':
        cash -= (event['price'] * event['quantity'] + event['fee']) * fx
    elif event['event_type'] == 'SELL':
        cash += (event['price'] * event['quantity'] - event['fee']) * fx
    elif event['event_type'] == 'SHORT':
        cash += (event['price'] * event['quantity'] - event['fee']) * fx
    elif event['event_type'] == 'COVER':
        cash -= (event['price'] * event['quantity'] + event['fee']) * fx
    elif event['event_type'] == 'INCOME':
        cash += event['amount'] * fx

    # Detect capital injection: cash went negative → external deposit needed
    if cash < 0:
        injection = abs(cash)
        external_flows.append((event['date'], injection))
        cash = 0.0
```

**Intraday ordering:** Same-day events are processed with SELL/SHORT first (cash inflows), then INCOME, then BUY/COVER (cash outflows). This minimizes false injection detection when a sell funds a same-day buy (common rebalancing pattern).

**Why this works:**
- All trades are internal transfers (cash ↔ positions). NAV = positions + cash stays stable at execution.
- Income is part of the same event stream, so dividends received before a buy reduce the injection needed.
- When a BUY requires more cash than available (e.g., initial purchase or new deposit), cash goes negative → external inflow detected.
- SHORT/COVER are purely internal: short proceeds add to cash, short liability appears as negative position value. NAV unchanged.
- External outflows (withdrawals) are undetectable from transaction data alone (documented limitation).

### Step 6: Compute Monthly Returns (Modified Dietz — Cash-Inclusive NAV)

**NAV includes both positions and derived cash balance.** External flows are capital injections detected when cash goes negative during trade replay.

For each month:
```
CF_i = external capital injections detected in this month (always positive = inflow)
W_i  = (D - d_i) / D   where D = days in month, d_i = day of flow (0-indexed from month start)
V_adjusted = V_start + Σ(CF_i × W_i)

monthly_return = (V_end - V_start - Σ(CF_i)) / V_adjusted
```

**Note:** Income is already captured in the NAV via cash_balance (income increases cash → increases NAV). No separate income_month term in the formula since it flows through V_end naturally.

**Fees:** Already reflected in cash balance from Step 5b.

**Why shorts work correctly:**
- Opening: SHORT 100 @ $100. Cash += $10k, position = -$10k. NAV unchanged. No external CF.
- Month-end: stock drops to $90. NAV = cash($10k) + position(-$9k) = $1k gain. Return positive. ✓
- Cover: Cash -= $9k, position closed. NAV = $1k realized profit in cash. ✓

Special cases:
- `V_start = 0` (first month): All initial buys trigger cash < 0, so external CFs are detected. `return = (V_end - 0 - Σ(CF_i)) / Σ(CF_i × W_i)` ← gain on invested capital.
- `V_adjusted ≤ 0`: skip month (return = 0, add warning). Should be rare since external CFs are always positive.

### Step 7: Feed into Metrics Engine
- Build `pd.Series` of monthly returns with DatetimeIndex (month-end dates)
- Fetch benchmark returns via `fetch_monthly_close(benchmark_ticker, ...)`
- Compute benchmark monthly returns via `calc_monthly_returns()`
- Align portfolio and benchmark returns (inner join on DatetimeIndex, drop NaN)
- Fetch risk-free rate via `fetch_monthly_treasury_rates()` (same as existing adapter in `portfolio_risk.py`)
- Call `compute_performance_metrics(portfolio_returns, benchmark_returns, risk_free_rate, ...)`
- Validate engine preconditions: same index, no NaN, DatetimeIndex

### Step 8: Add Realized-Specific Metadata
Augment the base metrics dict with:
- `realized_pnl`: total realized P&L from FIFO closed trades (`sum(ct.pnl_dollars for ct in fifo_result.closed_trades)`)
- `unrealized_pnl`: sum of (current_price - avg_cost) × shares for open positions
- `net_contributions`: Σ(buy_amounts) - Σ(sell_amounts) over full period (in USD)
- `income`: breakdown of dividend/interest income:
  - `total`: total dividends + interest over full period
  - `dividends`: total dividend income
  - `interest`: total interest income
  - `by_month`: {YYYY-MM: amount} from `IncomeAnalysis.by_month`
  - `by_symbol`: {ticker: amount} from `IncomeAnalysis.by_symbol`
  - `current_monthly_rate`: trailing 3-month avg from `IncomeAnalysis`
  - `projected_annual`: annualized from current rate
  - `yield_on_cost`: (projected_annual / total_cost_basis) × 100
  - `yield_on_value`: (projected_annual / current_portfolio_value) × 100
- `data_coverage`: (positions_with_full_history / total_positions) × 100
- `inception_date`: earliest transaction date (ISO string)
- `synthetic_positions`: list of `{ticker, currency, direction}` dicts with synthetic starting entries
- `source_breakdown`: {plaid: N, snaptrade: M} transaction counts from `fifo_transactions`
- `data_warnings`: list of any warnings (skipped months, FX fallbacks, invested-sleeve note, etc.)

Note: Dividends and interest are included in the Modified Dietz return numerator (Step 6), so `total_return` and `annualized_return` reflect income. The `income` section provides the breakdown for investors who want to see the yield separately.

---

## File Changes

| File | Action | What |
|------|--------|------|
| `core/realized_performance_analysis.py` | **CREATE** | Core pipeline: position reconstruction, monthly values, return series |
| `services/portfolio_service.py` | **MODIFY** | Add `analyze_realized_performance()` service method with caching |
| `mcp_tools/performance.py` | **MODIFY** | Add `mode` + `source` params, return `position_result` from helper, route realized path through `PortfolioService` |
| `mcp_server.py` | **MODIFY** | Add `mode` + `source` params to `get_performance()` wrapper, forward to inner function |
| `mcp_tools/README.md` | **MODIFY** | Document new `mode` parameter on `get_performance` |
| `tests/core/test_realized_performance_analysis.py` | **CREATE** | Unit tests for core pipeline |

---

## Core Module: `core/realized_performance_analysis.py`

### Functions

```python
def build_position_timeline(
    fifo_transactions: List[Dict[str, Any]],  # from TradingAnalyzer.fifo_transactions (has currency)
    current_positions: Dict[str, Dict],  # ticker → {shares, currency, cost_basis, ...}
    inception_date: datetime,
    incomplete_trades: List[IncompleteTrade],  # from FIFOMatcherResult.incomplete_trades
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[Tuple[str, str, str], List[Tuple[datetime, float]]], List[Dict], List[str]]:
    """
    Walk transactions forward to reconstruct position quantities over time.
    Key: (ticker, currency, direction) to match FIFO's internal keying.
    Returns: (position_events, synthetic_positions, warnings)
    - synthetic_positions: List of {ticker, currency, direction} dicts
    """

def derive_cash_and_external_flows(
    fifo_transactions: List[Dict[str, Any]],
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
) -> Tuple[List[Tuple[datetime, float]], List[Tuple[datetime, float]]]:
    """
    Replay all events (trades + income) in unified chronological stream to
    derive running cash balance and detect external capital injections.
    Same-day ordering: SELL/SHORT first, then INCOME, then BUY/COVER
    (minimizes false injection detection during rebalancing).
    Returns: (cash_snapshots, external_flows)
    - cash_snapshots: [(date, cash_balance_after)] at each event
    - external_flows: [(date, injection_amount)] when cash goes negative
    """

def compute_monthly_nav(
    position_timeline: Dict[Tuple[str, str, str], List],
    month_ends: List[datetime],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    cash_snapshots: List[Tuple[datetime, float]],
) -> pd.Series:
    """
    Compute month-end NAV = positions_value + cash_balance.
    LONG positions: +shares × price × fx_rate
    SHORT positions: -shares × price × fx_rate
    Cash: derived from trade replay (includes short proceeds, fees, income)
    Returns: pd.Series of portfolio NAV indexed by month-end dates.
    """

def compute_monthly_external_flows(
    external_flows: List[Tuple[datetime, float]],
    month_ends: List[datetime],
) -> Tuple[pd.Series, pd.Series]:
    """
    Aggregate detected external capital injections by month.
    Returns: (net_flows, time_weighted_flows)
    - net_flows: total injections per month
    - time_weighted_flows: Modified Dietz weighted injections per month
    """

def compute_monthly_returns(
    monthly_nav: pd.Series,
    net_flows: pd.Series,
    time_weighted_flows: pd.Series,
) -> Tuple[pd.Series, List[str]]:
    """
    Modified Dietz monthly returns with cash-inclusive NAV.
    Income already reflected in NAV via cash balance.
    Returns: (returns_series, warnings)
    Handles V_start=0 and V_adjusted<=0 edge cases.
    """

def analyze_realized_performance(
    positions: "PositionResult",
    user_email: str,
    benchmark_ticker: str = "SPY",
    source: str = "all",
) -> Dict[str, Any]:
    """
    Main orchestrator. Fetches transactions, reconstructs positions,
    builds monthly returns, calls compute_performance_metrics(),
    adds realized-specific metadata.
    Returns: dict with base metrics + realized metadata, or error dict.
    """
```

### Dependencies
- `trading_analysis.data_fetcher` — `fetch_all_transactions()`, `fetch_snaptrade_activities()`, `fetch_plaid_transactions()`
- `trading_analysis.analyzer` — `TradingAnalyzer` for normalization + FIFO transaction dicts
- `trading_analysis.fifo_matcher` — `FIFOMatcher`, `FIFOMatcherResult`, `IncompleteTrade`, `ClosedTrade`
- `trading_analysis.models` — `NormalizedIncome`, `IncomeAnalysis`
- `core.performance_metrics_engine` — `compute_performance_metrics()`
- `data_loader` — `fetch_monthly_close()`, `calc_monthly_returns()`, `fetch_monthly_treasury_rates()`
- `fmp/fx.py` — `get_monthly_fx_series()` for batch historical FX, `get_spot_fx_rate()` for current-day only

---

## MCP Integration: `mcp_tools/performance.py` + `mcp_server.py`

### `mcp_tools/performance.py` changes

Add `mode` and `source` params. Modify `_load_portfolio_for_performance()` to also return `position_result`:

```python
def _load_portfolio_for_performance(user_email, portfolio_name, use_cache=True):
    # ... existing code ...
    return user, user_id, portfolio_data, position_result  # ← add position_result

def get_performance(
    user_email: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    benchmark_ticker: str = "SPY",
    mode: Literal["hypothetical", "realized"] = "hypothetical",
    source: Literal["all", "snaptrade", "plaid"] = "all",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
```

**Routing logic:**
```python
if mode == "hypothetical":
    # Existing path — unchanged (ignore source param)
    result = PortfolioService(cache_results=use_cache).analyze_performance(
        portfolio_data, benchmark_ticker=benchmark_ticker
    )
    # ... existing format handling ...
elif mode == "realized":
    # Route through PortfolioService for caching/error parity
    realized_result = PortfolioService(cache_results=use_cache).analyze_realized_performance(
        position_result=position_result,
        user_email=user,
        benchmark_ticker=benchmark_ticker,
        source=source,
    )
    # ... format handling for realized results ...
```

### `mcp_server.py` changes

Update the wrapper to pass through new params:
```python
@mcp.tool()
def get_performance(
    portfolio_name: str = "CURRENT_PORTFOLIO",
    benchmark_ticker: str = "SPY",
    mode: Literal["hypothetical", "realized"] = "hypothetical",
    source: Literal["all", "snaptrade", "plaid"] = "all",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
    """..."""
    return _get_performance(
        user_email=None,
        portfolio_name=portfolio_name,
        benchmark_ticker=benchmark_ticker,
        mode=mode,
        source=source,
        format=format,
        use_cache=use_cache
    )
```

### Summary Format (mode="realized")
Same top-level keys as hypothetical for parity + realized extras:
```python
{
    "status": "success",
    "mode": "realized",
    "total_return": float,
    "annualized_return": float,
    "volatility": float,
    "sharpe_ratio": float,
    "max_drawdown": float,
    "win_rate": float,
    "analysis_years": float,
    "benchmark_ticker": str,
    "alpha_annual": float,
    "beta": float,
    "performance_category": str,
    "key_insights": [str],
    # Realized-specific
    "realized_pnl": float,
    "unrealized_pnl": float,
    "income_total": float,           # total dividends + interest
    "income_yield_on_cost": float,   # projected annual income / cost basis (%)
    "income_yield_on_value": float,  # projected annual income / current value (%)
    "data_coverage": float,
    "inception_date": str,
}
```

### Full Format (mode="realized")
Base performance metrics (same structure as hypothetical full) + `realized_metadata` section with all Step 8 fields.

### Report Format (mode="realized")
Same formatted text layout as hypothetical report + "REALIZED PERFORMANCE DETAILS" section.

### Backward Compatibility
- Default `mode="hypothetical"` means all existing callers get identical behavior
- `source` param is ignored when `mode="hypothetical"`
- Summary/full/report formats produce the same keys for hypothetical mode
- `_load_portfolio_for_performance()` returns additional `position_result` — all callers updated

---

## Implementation Sequence

### Phase 1: Core Pipeline
1. Create `core/realized_performance_analysis.py` with all functions
2. Position reconstruction using `fifo_transactions` dicts (preserving currency) with `(ticker, currency, direction)` keying
3. Synthetic position identification: current holdings at inception, FIFO incomplete trades at/before their trade dates
4. Income currency mapping via symbol→currency lookup from transactions + positions
5. Cash balance derivation and external flow detection (cash goes negative → capital injection)
6. Month-end NAV = positions + cash, with batch price fetching (`fetch_monthly_close`) and batch FX series (`get_monthly_fx_series`)
7. Modified Dietz monthly returns with cash-inclusive NAV and detected external CFs
8. Wire to `compute_performance_metrics()` with benchmark alignment + risk-free rate
9. Add realized metadata from FIFO results + income analysis

### Phase 2: Service + MCP Integration
1. Add `analyze_realized_performance()` to `PortfolioService` (caching, error wrapping)
2. Modify `mcp_tools/performance.py` — add `mode` + `source` params, return `position_result` from helper, route realized through `PortfolioService`
3. Modify `mcp_server.py` — add `mode` + `source` params to wrapper, forward to inner function
4. Update `mcp_tools/README.md` with new `mode` parameter documentation

### Phase 3: Tests
1. Unit tests for position reconstruction (synthetic starts at correct dates, incomplete trades, multi-ticker, multi-currency, direction-aware)
2. Unit tests for cash derivation + external flow detection (known trades → known cash balance + injections)
3. Unit tests for Modified Dietz returns (known NAV + known CFs → known returns, including SHORT/COVER with fees)
3. Unit tests for V_start=0 and V_adjusted≤0 edge cases
4. Unit tests for FX conversion in flows and valuations
5. Unit tests for income currency mapping
6. Adapter tests: full pipeline with mocked I/O
7. MCP tool tests: hypothetical mode unchanged, realized mode summary/full/report + error case

---

## Edge Cases

1. **No transaction history AND no positions**: Return error dict `{"status": "error", "message": "..."}`
2. **No transactions but positions exist**: inception_date = 12 months ago, all synthetic, data_coverage=0%, return success with warning
3. **Single month of data**: Insufficient for CAPM (fallback alpha=0, beta=1, r²=0), return basic metrics
4. **Multi-currency**: Price in native currency, convert to USD via `get_monthly_fx_series()` for historical, `get_spot_fx_rate()` for current
5. **Short positions**: SHORT/COVER are internal (cash ↔ position). Short proceeds increase cash; short liability is negative position value. NAV = positions + cash is unchanged at execution. Returns come from position value changes.
6. **V_start = 0 (first month or after liquidation)**: Modified Dietz with time-weighted inflows as denominator
7. **V_adjusted ≤ 0**: Skip month (return = 0, add warning)
8. **Position goes to 0 then reappears**: Transaction timeline handles naturally
9. **Corporate actions (splits)**: Not handled Phase 1; document as limitation
10. **Ticker in transactions but not in current positions (fully sold)**: Still included in historical reconstruction
11. **Income in non-USD currency**: Infer currency from symbol→currency map, convert via `fx_cache`
12. **FIFO incomplete trades**: Synthetic entry placed at/before the incomplete trade date (not at inception), using `IncompleteTrade.direction` for correct position type
13. **`source` filter**: Filters transactions only; positions are always fetched consolidated. Runtime warning added when `source != "all"`. Documented as limitation that cross-provider position splits aren't handled.

---

## Known Limitations

1. **No withdrawal detection**: External outflows (money withdrawn from brokerage) cannot be detected from transaction data alone. Cash from sells accumulates in NAV. Returns may be slightly understated if significant withdrawals occurred.
2. **Capital injection heuristic**: External inflows are detected when the derived cash balance goes negative. This works well for initial deposits and subsequent top-ups, but may miss deposits made when cash was already positive (e.g., selling stock, depositing more, then buying).
3. **Corporate actions**: Stock splits not handled; may distort historical price/quantity alignment.
4. **Source filter granularity**: `source` param filters transactions but not positions (positions are always cross-provider consolidated). A runtime warning is added when `source != "all"` to flag this limitation.
5. **Income currency**: Inferred from trade history (symbol→currency map), not directly from income events. May be wrong for edge cases where a ticker is cross-listed across venues in different currencies.

---

## Verification

1. Unit tests: deterministic transaction fixtures → exact known monthly returns
2. Sanity check: compare `get_performance(mode="realized")` vs `get_performance(mode="hypothetical")` on overlapping periods
3. NAV identity check: `V_end = V_start + Σ(external_flows) + portfolio_gain + income` (within FX/rounding tolerance)
4. MCP tool: test all three formats in both modes + error cases
5. Manual: run with real portfolio data, verify numbers are reasonable
