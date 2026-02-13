# Tax Loss Harvesting MCP Tool - Implementation Plan

> **Status:** NOT STARTED

## Overview

Expose tax-loss harvesting suggestions via a new `suggest_tax_loss_harvest` MCP tool on the `portfolio-mcp` server. The tool combines existing FIFO lot-level data with live market prices to identify unrealized loss candidates, classify them by holding period (short-term vs long-term), and flag wash sale risk from recent transactions.

## Use Cases & Example Queries

This tool answers questions about tax-saving opportunities from unrealized losses in the portfolio. Example natural language queries:

- **"Where can I save on taxes this year?"** -- `suggest_tax_loss_harvest()` identifies all positions with unrealized losses, sorted by largest loss amount
- **"Which positions have the biggest unrealized losses?"** -- `suggest_tax_loss_harvest(sort_by="loss_pct")` shows the worst-performing lots by percentage
- **"Any tax loss harvesting opportunities before year-end?"** -- `suggest_tax_loss_harvest()` returns candidates with short-term vs long-term classification so the user can prioritize before December 31
- **"Show me short-term losses I could harvest"** -- `suggest_tax_loss_harvest()` classifies every lot by holding period; the agent filters the results to short-term candidates (< 365 days held)
- **"What wash sale risks do I have?"** -- `suggest_tax_loss_harvest(include_wash_sale_check=True)` flags any lots where same-ticker purchases occurred within the 30-day wash sale window

### Tool Chaining Example

A comprehensive request like **"Optimize my tax situation"** would chain multiple tools:

1. `suggest_tax_loss_harvest()` -- find the best harvest candidates (largest losses, wash-sale-clear)
2. `screen_stocks(sector="<same sector as candidate>")` -- find replacement stocks in the same sector to maintain exposure while avoiding wash sale rules
3. `run_whatif(delta_changes={"<harvested ticker>": -current_weight, "<replacement>": +current_weight})` -- check the impact on portfolio risk of swapping the harvested position for the replacement

The agent walks the user through identifying losses, finding suitable replacements, and validating that the swap does not materially alter the portfolio's risk profile.

---

No new FMP endpoints are needed. All required infrastructure already exists:
- **FIFO lot matching**: `trading_analysis/fifo_matcher.py` (`FIFOMatcher`, `OpenLot`, `FIFOMatcherResult`)
- **Transaction loading**: `trading_analysis/data_fetcher.py` (`fetch_all_transactions`, `fetch_snaptrade_activities`, `fetch_plaid_transactions`)
- **Transaction normalization**: `trading_analysis/analyzer.py` (`TradingAnalyzer` normalizes raw provider data into `fifo_transactions`)
- **Current positions**: `services/position_service.py` (`PositionService.get_all_positions()`)
- **Current prices**: `utils/ticker_resolver.py` (`fetch_fmp_quote_with_currency`) and `fmp/fx.py` (`get_spot_fx_rate`)
- **User resolution**: `mcp_tools/risk.py` (`_resolve_user_id`)

## Tool: `suggest_tax_loss_harvest`

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user_email` | `Optional[str]` | `None` | User to analyze. Uses `RISK_MODULE_USER_EMAIL` env var if not provided. |
| `min_loss` | `Optional[float]` | `None` | Minimum unrealized loss (USD, positive absolute value, e.g. 500 = $500). `None` = show all losses. Validated >= 0. |
| `sort_by` | `Literal["loss_amount", "loss_pct", "days_held"]` | `"loss_amount"` | Sort order for candidates. |
| `include_wash_sale_check` | `bool` | `True` | Check for wash sale risk (same-ticker purchases within 30 days). Note: does NOT detect "substantially identical" securities. |
| `source` | `Literal["all", "snaptrade", "plaid"]` | `"all"` | Transaction source filter. |
| `format` | `Literal["full", "summary", "report"]` | `"summary"` | Output format. |
| `use_cache` | `bool` | `True` | Use cached position data when available. |

### Flow

```
1. Resolve user (email -> user_id)
2. Fetch current positions (PositionService)
3. Fetch transaction history (same pattern as realized performance)
4. Run FIFO matching -> get open lots
5. Fetch current prices for all open-lot tickers
6. Calculate unrealized gain/loss per lot
7. Filter to lots with unrealized losses (>= min_loss if set; min_loss is always positive USD threshold)
8. Classify each lot: short-term (held <= 1 year by date) vs long-term (held > 1 year by date)
9. If include_wash_sale_check: scan transactions for wash sale risk
10. Sort, format, return
```

## Detailed Design

### Step 1-2: User Resolution + Position Fetch

Reuse exact pattern from `mcp_tools/performance.py` (`_load_portfolio_for_performance`):

```python
user = user_email or get_default_user()
user_id = _resolve_user_id(user)
position_service = PositionService(user)
position_result = position_service.get_all_positions(
    use_cache=use_cache,
    force_refresh=not use_cache,
    consolidate=True
)
```

Positions are needed for two reasons:
1. Cross-reference against FIFO open lots (sanity check)
2. Access `fmp_ticker` mappings for price fetching

### Step 3: Fetch Transaction History

Same pattern as `core/realized_performance_analysis.py` (`_fetch_transactions_for_source`):

```python
from trading_analysis.data_fetcher import fetch_all_transactions, fetch_snaptrade_activities, fetch_plaid_transactions

if source == "all":
    payload = fetch_all_transactions(user)
elif source == "snaptrade":
    payload = {"snaptrade_activities": fetch_snaptrade_activities(user), ...}
elif source == "plaid":
    plaid_payload = fetch_plaid_transactions(user)
    payload = {"plaid_transactions": plaid_payload.get("transactions", []), ...}

analyzer = TradingAnalyzer(
    plaid_securities=payload.get("plaid_securities", []),
    plaid_transactions=payload.get("plaid_transactions", []),
    snaptrade_activities=payload.get("snaptrade_activities", []),
    use_fifo=True,
)
fifo_transactions = list(analyzer.fifo_transactions)
```

### Step 4: Run FIFO Matching

```python
from trading_analysis.fifo_matcher import FIFOMatcher

matcher = FIFOMatcher()
fifo_result = matcher.process_transactions(fifo_transactions)
# fifo_result.open_lots: Dict[(symbol, currency, direction), List[OpenLot]]
```

Key data from `OpenLot`:
- `symbol`, `entry_date`, `entry_price`, `remaining_quantity`, `currency`, `direction`

### Step 5: Fetch Current Prices

For each unique ticker in open lots, fetch the current market price using the same approach as `PositionService._calculate_market_values()`:

```python
from utils.ticker_resolver import fetch_fmp_quote_with_currency, normalize_fmp_price, normalize_currency
from fmp.fx import get_spot_fx_rate

def _fetch_current_prices(
    open_lots: Dict[Tuple[str, str, str], List[OpenLot]],
    fmp_ticker_map: Dict[str, str],
) -> Tuple[Dict[Tuple[str, str], PriceInfo], List[str]]:
    """Fetch current price and FX rate for each (ticker, currency) in open lots.

    [Codex review fix] Key by (symbol, currency) not just symbol, to handle
    edge case of same ticker in different currencies.

    Returns:
        (prices_dict, skipped_tickers)
        prices_dict: {(symbol, currency) -> PriceInfo(local_price, usd_price, fx_rate)}
        skipped_tickers: list of tickers where price fetch failed
    """
    prices = {}
    skipped = []
    seen = set()

    for (symbol, currency, direction), lots in open_lots.items():
        key = (symbol, currency)
        if key in seen:
            continue
        seen.add(key)

        fmp_symbol = fmp_ticker_map.get(symbol, symbol)
        try:
            raw_price, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
            if raw_price is None:
                skipped.append(symbol)
                continue
            local_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)
            base_currency = normalize_currency(base_currency)
            fx_rate = 1.0
            if base_currency and base_currency.upper() != "USD":
                fx_rate = get_spot_fx_rate(base_currency)
            usd_price = local_price * fx_rate
            prices[key] = {"local_price": local_price, "usd_price": usd_price, "fx_rate": fx_rate}
        except Exception:
            skipped.append(symbol)
            continue

    return prices, skipped
```

The `fmp_ticker_map` is built from `position_result.data.positions` (each position has an `fmp_ticker` field), same pattern as `_build_current_positions` in `core/realized_performance_analysis.py`.

### Step 6: Calculate Unrealized Gain/Loss Per Lot

For each open lot, compute:

```python
from datetime import datetime

today = datetime.now()

from dateutil.relativedelta import relativedelta

today = datetime.now()

for (symbol, currency, direction), lots in fifo_result.open_lots.items():
    price_key = (symbol, currency)
    if price_key not in current_prices:
        continue

    price_info = current_prices[price_key]
    current_local = price_info["local_price"]
    current_usd = price_info["usd_price"]
    fx_rate = price_info["fx_rate"]

    for lot in lots:
        # [Codex review fix] Use entry-date FX for basis (tax-correct).
        # get_monthly_fx_series() provides historical rates; fall back to current FX.
        entry_fx = _get_historical_fx_rate(currency, lot.entry_date) or fx_rate

        # Entry cost in USD (using entry-date FX)
        entry_cost_usd = lot.entry_price * lot.remaining_quantity * entry_fx

        # Current value in USD (using current FX)
        current_value_usd = current_usd * lot.remaining_quantity

        # P&L direction
        if direction == "LONG":
            unrealized_pnl = current_value_usd - entry_cost_usd
        else:  # SHORT
            unrealized_pnl = entry_cost_usd - current_value_usd

        unrealized_pnl_pct = (unrealized_pnl / entry_cost_usd * 100) if entry_cost_usd > 0 else 0

        # [Codex review fix] Holding period uses date arithmetic, not day count.
        # Long-term = held MORE than 1 year (sale_date > acquisition_date + 1 year)
        days_held = (today - lot.entry_date).days
        one_year_anniversary = lot.entry_date + relativedelta(years=1)
        holding_period = "long_term" if today > one_year_anniversary else "short_term"
```

### Step 7: Filter to Loss Lots

```python
if unrealized_pnl < 0:
    loss_amount = abs(unrealized_pnl)
    if min_loss is not None and loss_amount < min_loss:
        continue  # Below threshold
    # Add to candidates list
```

### Step 8: Short-Term vs Long-Term Classification

**[Codex review fix]** Uses date arithmetic (not raw day count) per IRS rules:
- **Short-term**: `today <= entry_date + 1 year`. Losses offset short-term gains (taxed at ordinary income rates), making them more valuable per dollar.
- **Long-term**: `today > entry_date + 1 year`. Losses offset long-term gains (taxed at preferential capital gains rates).

Uses `dateutil.relativedelta(years=1)` for correct leap year handling. Output includes both `holding_period` and `days_held` for context.

### Step 9: Wash Sale Detection

A wash sale occurs when a "substantially identical" security is bought within 30 days before or after a sale at a loss. For tax-loss harvesting suggestions, we check:

1. **Recent buys of the same ticker**: Scan `fifo_transactions` for BUY of the same symbol within the last 30 days.
2. **Recent sells of the same ticker**: If the user sells to harvest and then re-buys within 30 days, the loss is disallowed. We flag recent buy activity as a forward-looking risk.

```python
from datetime import timedelta

def _check_wash_sale_risk(
    fifo_transactions: List[Dict],
    symbol: str,
    as_of: datetime,
    window_days: int = 30,
) -> Dict[str, Any]:
    """Check wash sale risk for a potential harvest candidate.

    [Codex review fix] Removed unused closed_trades param. Same-ticker only.
    Scans for BUY of the same symbol within 30 days before as_of.
    Forward-looking (30 days after) is advisory only.

    Returns:
        Dict with wash_sale_risk (bool), reason (str), recent_transactions (list)
    """
    window_start = as_of - timedelta(days=window_days)

    recent_buys = []
    for txn in fifo_transactions:
        txn_symbol = txn.get("symbol", "")
        txn_type = txn.get("type", "").upper()
        txn_date = txn.get("date")

        if txn_symbol != symbol:
            continue
        if txn_type != "BUY":
            continue

        if isinstance(txn_date, datetime):
            if window_start <= txn_date <= as_of:
                recent_buys.append({
                    "date": txn_date.strftime("%Y-%m-%d"),
                    "type": txn_type,
                    "quantity": txn.get("quantity", 0),
                    "price": txn.get("price", 0),
                })

    if recent_buys:
        total_shares = sum(b["quantity"] for b in recent_buys)
        return {
            "wash_sale_risk": True,
            "reason": f"{len(recent_buys)} buy(s) of {symbol} ({total_shares} shares) within 30-day window",
            "recent_transactions": recent_buys,
        }

    return {
        "wash_sale_risk": False,
        "reason": None,
        "recent_transactions": [],
    }
```

**Scope limitation**: "Substantially identical" securities (e.g., selling VTI and buying VOO) require judgment beyond simple ticker matching. The tool flags same-ticker wash sale risk only and includes a disclaimer about substantially identical securities. This can be enhanced in a future version with ETF-overlap or peer-group data.

**[Codex review fix] Cross-source wash sale:** Wash sale detection ALWAYS scans ALL transaction sources (both Plaid and SnapTrade), regardless of the `source` param used for FIFO lot construction. The `source` param filters which lots to analyze, but wash sale risk from any account is relevant. Implementation: load `fetch_all_transactions(user)` separately for wash sale scan when `source != "all"`.

**[Codex review fix] Coverage reporting:** Add `data_coverage` percentage and `positions_without_lots` list to output. Positions in current holdings that have no matching FIFO open lots (pre-data-window buys) are listed with a note. Coverage = `positions_with_lots / total_equity_positions * 100`.

### Step 10: Sort and Format

Sort candidates according to `sort_by`:
- `"loss_amount"`: Largest absolute loss first (default — most impactful for tax purposes)
- `"loss_pct"`: Largest percentage loss first (worst performers)
- `"days_held"`: Longest-held first (may indicate fundamental thesis failure)

## Output Structures

### Summary Format

```python
{
    "status": "success",
    "total_harvestable_loss": -4523.50,
    "short_term_loss": -1200.00,
    "long_term_loss": -3323.50,
    "candidate_count": 8,
    "candidates": [
        {
            "ticker": "INTC",
            "direction": "LONG",
            "lot_date": "2024-03-15",
            "days_held": 694,
            "holding_period": "long_term",
            "shares": 100.0,
            "cost_basis_per_share": 42.50,
            "current_price": 28.75,
            "cost_basis_total": 4250.00,
            "current_value": 2875.00,
            "unrealized_loss": -1375.00,
            "unrealized_loss_pct": -32.35,
            "wash_sale_risk": false
        },
        # ... more candidates, sorted by sort_by
    ],
    "wash_sale_warnings": [
        {
            "ticker": "SOFI",
            "reason": "2 buy(s) of SOFI within 30-day window",
            "recent_transactions": [
                {"date": "2026-01-20", "type": "BUY", "quantity": 50, "price": 11.25}
            ]
        }
    ],
    "data_coverage_pct": 85.0,
    "positions_without_lots": ["XYZ"],
    "skipped_tickers": [],
    "metadata": {
        "as_of": "2026-02-07",
        "source": "all",
        "min_loss_filter": null,
        "sort_by": "loss_amount",
        "positions_analyzed": 22,
        "positions_with_lots": 18,
        "wash_sale_scope": "same-ticker only, all sources",
        "lots_with_approximate_fx": 0
    },
    "disclaimer": "This is informational only and not tax advice. Consult a tax professional. Wash sale detection covers same-ticker trades only, not substantially identical securities."
}
```

### Full Format

Extends summary with:
```python
{
    # ... all summary fields ...
    "all_lots_with_losses": [
        # Every lot with unrealized loss (not just top candidates)
        # Includes lots below min_loss threshold for completeness
    ],
    "lots_with_gains": [
        # Summary of lots with unrealized gains (for context)
        {
            "ticker": "AAPL",
            "total_unrealized_gain": 5230.00,
            "lot_count": 3,
            "short_term_count": 1,
            "long_term_count": 2,
        }
    ],
    "portfolio_tax_summary": {
        "total_unrealized_gain": 15200.00,
        "total_unrealized_loss": -4523.50,
        "net_unrealized": 10676.50,
        "short_term_gain": 3200.00,
        "short_term_loss": -1200.00,
        "long_term_gain": 12000.00,
        "long_term_loss": -3323.50,
    },
    "wash_sale_details": [
        # Full wash sale analysis per candidate
    ]
}
```

### Report Format

Human-readable text report:
```
TAX-LOSS HARVESTING OPPORTUNITIES
==================================
As of: 2026-02-07

SUMMARY
• Total harvestable loss: -$4,523.50
• Short-term losses: -$1,200.00 (offsets ordinary income)
• Long-term losses: -$3,323.50 (offsets capital gains)
• Candidates: 8 lots across 5 tickers

TOP CANDIDATES
Ticker    Lot Date    Days  Period      Shares   Cost      Current   Loss        Loss%
INTC      2024-03-15   694  Long-term   100.0    $42.50    $28.75    -$1,375.00  -32.4%
...

WASH SALE WARNINGS
⚠️ SOFI: 2 buy(s) within 30-day window
   - 2026-01-20: BUY 50 shares @ $11.25

DISCLAIMER
This is informational only and not tax advice. ...
```

## Files to Create/Modify

### New File

1. **`mcp_tools/tax_harvest.py`** — Core tool implementation

Contains:
- `_fetch_current_prices()` — price fetching for open lot tickers, keyed by (symbol, currency)
- `_get_historical_fx_rate()` — entry-date FX lookup via `get_monthly_fx_series()`
- `_build_fmp_ticker_map()` — extract fmp_ticker from positions
- `_check_wash_sale_risk()` — same-ticker wash sale detection (always cross-source)
- `_classify_lot()` — per-lot unrealized P&L + holding period (date arithmetic)
- `_format_report()` — human-readable text report builder
- `suggest_tax_loss_harvest()` — main tool function

### New Test File

2. **`tests/mcp_tools/test_tax_harvest.py`** — Automated unit tests (~200 lines)
   - `_analyze_open_lots` with known lots (verify math)
   - FX conversion with entry-date vs current FX
   - Short position lots excluded (v1 LONG-only verification)
   - Holding period classification (leap year edge case)
   - Wash sale detection (recent buy flagged, old buy not)
   - Cross-source wash sale (plaid buy flagged when source=snaptrade)
   - `min_loss` threshold filtering
   - All-gains scenario (0 candidates)
   - Format variants (summary, full, report)

### Modified Files

3. **`mcp_server.py`** — Import + `@mcp.tool()` registration (tool #11)
4. **`mcp_tools/__init__.py`** — Import + `__all__` export
5. **`mcp_tools/README.md`** — Document new tool

## Error Handling

| Error | Handling |
|-------|----------|
| No user configured | `{"status": "error", "error": "No user specified and RISK_MODULE_USER_EMAIL not configured"}` |
| No brokerage positions | `{"status": "error", "error": "No brokerage positions found."}` |
| No transaction history | **[Codex R2 fix]** `{"status": "success", "candidate_count": 0, "data_coverage_pct": 0, "note": "No transaction history available. Connect brokerage accounts for lot-level analysis."}` |
| No open lots from FIFO | `{"status": "success", "candidate_count": 0, "candidates": [], ...}` (not an error) |
| No lots with losses | `{"status": "success", "candidate_count": 0, "candidates": [], "total_harvestable_loss": 0}` |
| Price fetch fails for a ticker | Skip that ticker, add to `skipped_tickers` list in output |
| All price fetches fail | `{"status": "error", "error": "Unable to fetch current prices for any holdings."}` |
| Invalid source param | `{"status": "error", "error": "source must be one of: all, snaptrade, plaid"}` |

## Edge Cases

1. **Short positions**: **[Codex R2 fix]** v1 scopes tax-loss harvest to LONG lots only. Short positions have inverted P&L and their wash sale semantics are more complex (COVER vs BUY direction matching). Short lot support deferred to v2 with direction-aware wash sale logic.

2. **Multi-currency lots**: **[Codex R2 fix]** Entry basis uses entry-date FX via `_get_historical_fx_rate()` (monthly series). When historical FX is unavailable, falls back to current FX and sets `fx_approximated=True` per lot. Summary includes `lots_with_approximate_fx` count. Current value always uses current FX.

3. **Options**: FIFO matcher tracks options with synthetic symbols (e.g., `NNDM_C2_230406`). These will have open lots if not expired. Price fetching will likely fail for these symbols (no FMP quote), so they'll be skipped with a warning. This is acceptable since options tax treatment is complex.

4. **Incomplete trades**: `fifo_result.incomplete_trades` represent exits without matching entries (pre-data-window buys). These don't have open lots, so they don't affect tax-loss harvesting suggestions. No special handling needed.

5. **Cash proxy tickers**: Tickers like `SGOV` (mapped from `CUR:USD`) will have open lots if they have cost basis. These are valid harvest candidates.

6. **Zero-quantity lots**: `OpenLot.is_closed` returns True when `remaining_quantity <= 0.001`. Filter these out.

7. **Wash sale with inferred shorts**: v1 skips SHORT lots entirely. Wash sale detection only scans for BUY transactions (not COVER) since we only harvest LONG lots.

## MCP Server Registration

```python
# mcp_server.py additions

# Import (in stdout redirect block)
from mcp_tools.tax_harvest import suggest_tax_loss_harvest as _suggest_tax_loss_harvest

@mcp.tool()
def suggest_tax_loss_harvest(
    min_loss: Optional[float] = None,
    sort_by: Literal["loss_amount", "loss_pct", "days_held"] = "loss_amount",
    include_wash_sale_check: bool = True,
    source: Literal["all", "snaptrade", "plaid"] = "all",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Identify tax-loss harvesting opportunities from unrealized losses.

    Analyzes FIFO tax lots against current market prices to find positions
    with unrealized losses that could be sold to offset capital gains.
    Classifies lots as short-term or long-term and flags wash sale risk.

    Args:
        min_loss: Minimum unrealized loss in USD to include (optional).
            Only lots with losses >= this threshold are shown.
        sort_by: Sort order for candidates:
            - "loss_amount": Largest absolute loss first (default)
            - "loss_pct": Largest percentage loss first
            - "days_held": Longest-held lots first
        include_wash_sale_check: Check for wash sale risk from recent
            same-ticker purchases within 30 days (default: True).
        source: Transaction source filter:
            - "all": Plaid + SnapTrade
            - "snaptrade": SnapTrade only
            - "plaid": Plaid only
        format: Output format:
            - "summary": Top candidates with loss amounts and wash sale warnings
            - "full": All lots with gains/losses and complete tax summary
            - "report": Human-readable formatted report
        use_cache: Use cached position data when available (default: True).

    Returns:
        Tax-loss harvesting suggestions with status field ("success" or "error").

    Examples:
        "Show tax loss harvesting opportunities" -> suggest_tax_loss_harvest()
        "What losses can I harvest over $500?" -> suggest_tax_loss_harvest(min_loss=500)
        "Tax loss candidates sorted by percentage" -> suggest_tax_loss_harvest(sort_by="loss_pct")
        "Full tax lot analysis" -> suggest_tax_loss_harvest(format="full")
    """
    return _suggest_tax_loss_harvest(
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
        min_loss=min_loss,
        sort_by=sort_by,
        include_wash_sale_check=include_wash_sale_check,
        source=source,
        format=format,
        use_cache=use_cache,
    )
```

## Implementation Details: `mcp_tools/tax_harvest.py`

```python
"""
MCP Tools: suggest_tax_loss_harvest

Identifies tax-loss harvesting opportunities from FIFO tax lots and
current market prices.

Usage (from Claude):
    "Show tax loss harvesting opportunities"
    "What losses can I harvest?"
    "Tax loss candidates sorted by percentage"

Architecture note:
- Uses FIFO open lots from transaction history (same path as realized performance)
- Current prices from FMP profile endpoint (same as PositionService)
- Wash sale detection: same-ticker BUY within 30-day window
- stdout redirected to stderr to protect MCP JSON-RPC channel
"""

import sys
from datetime import datetime, timedelta
from typing import Optional, Literal, Dict, List, Any, Tuple

from services.position_service import PositionService
from settings import get_default_user
from mcp_tools.risk import _resolve_user_id


def suggest_tax_loss_harvest(
    user_email: Optional[str] = None,
    min_loss: Optional[float] = None,
    sort_by: Literal["loss_amount", "loss_pct", "days_held"] = "loss_amount",
    include_wash_sale_check: bool = True,
    source: Literal["all", "snaptrade", "plaid"] = "all",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True,
) -> dict:
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # 1. Resolve user
        user = user_email or get_default_user()
        if not user:
            raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")
        user_id = _resolve_user_id(user)

        # 2. Fetch positions (for fmp_ticker map + cross-reference)
        position_service = PositionService(user)
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=not use_cache, consolidate=True
        )
        if not position_result.data.positions:
            raise ValueError("No brokerage positions found. Connect a brokerage account first.")

        fmp_ticker_map = _build_fmp_ticker_map(position_result)

        # 3. Fetch transactions + run FIFO
        fifo_transactions, fifo_result = _load_fifo_data(user, source)

        if not fifo_result.open_lots:
            return {
                "status": "success",
                "total_harvestable_loss": 0,
                "short_term_loss": 0,
                "long_term_loss": 0,
                "candidate_count": 0,
                "candidates": [],
                "wash_sale_warnings": [],
                "data_coverage_pct": 0,
                "positions_without_lots": [p["ticker"] for p in position_result.data.positions if p.get("type") != "cash"],
                "skipped_tickers": [],
                "note": "No FIFO open lots found. Transaction history may be incomplete.",
                "disclaimer": _DISCLAIMER,
            }

        # 4. Fetch current prices (returns tuple)
        current_prices, skipped_tickers = _fetch_current_prices(fifo_result.open_lots, fmp_ticker_map)
        ...  # (continued as described in flow)

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

The full implementation follows the flow described above. Key helper functions:

- `_load_fifo_data(user, source)` -> `(fifo_transactions, FIFOMatcherResult)` — mirrors `_fetch_transactions_for_source` + `TradingAnalyzer` + `FIFOMatcher.process_transactions()`
- `_fetch_current_prices(open_lots, fmp_ticker_map)` -> `(Dict[(symbol,currency), PriceInfo], skipped_tickers)` — price + FX per (ticker, currency)
- `_get_historical_fx_rate(currency, entry_date)` -> `Optional[float]` — entry-date FX from `get_monthly_fx_series()`. **[Codex R2 fix]** Uses nearest prior month-end rate to entry date (i.e., last available rate before or on entry_date). Returns None if unavailable → caller falls back to current FX and sets `fx_approximated=True` on that lot.
- `_build_fmp_ticker_map(position_result)` -> `Dict[str, str]` — ticker -> fmp_ticker
- `_classify_lots(open_lots, current_prices, min_loss)` -> `(loss_candidates, gain_summary, tax_summary)` — per-lot P&L + holding period
- `_check_wash_sale_risk(fifo_transactions, symbol, as_of)` -> wash sale dict
- `_format_report(candidates, wash_sale_warnings, tax_summary)` -> str

## Patterns Followed

| Pattern | Implementation |
|---------|---------------|
| stdout redirection | `sys.stdout = sys.stderr` in try/finally |
| Error handling | `try/except -> {"status": "error", "error": str(e)}` |
| Format switching | summary/full/report consistent structure |
| Tool registration | `@mcp.tool()` in `mcp_server.py` with full docstring + examples |
| Exports | `mcp_tools/__init__.py` imports + `__all__` |
| User resolution | `_resolve_user_id` from `mcp_tools.risk` |
| Transaction loading | Same pattern as `core/realized_performance_analysis.py` |
| Price fetching | Same pattern as `PositionService._calculate_market_values()` |
| No `user_email` in mcp_server.py | Uses `None` (env var fallback), consistent with all other tools |

## Verification Steps

1. **Import test**: `from mcp_tools.tax_harvest import suggest_tax_loss_harvest` — no import errors
2. **Summary default**: `suggest_tax_loss_harvest()` -> status: success, candidates listed
3. **Min loss filter**: `suggest_tax_loss_harvest(min_loss=500)` -> only losses >= $500
4. **Sort by loss_pct**: `suggest_tax_loss_harvest(sort_by="loss_pct")` -> sorted by % loss
5. **Sort by days_held**: `suggest_tax_loss_harvest(sort_by="days_held")` -> longest-held first
6. **Wash sale detection**: Verify wash sale warnings appear for tickers with recent buys
7. **Wash sale disabled**: `suggest_tax_loss_harvest(include_wash_sale_check=False)` -> no wash sale warnings
8. **Full format**: `suggest_tax_loss_harvest(format="full")` -> includes gains summary + tax summary
9. **Report format**: `suggest_tax_loss_harvest(format="report")` -> formatted text
10. **No losses**: All lots at a gain -> `candidate_count: 0`, `total_harvestable_loss: 0`
11. **Source filter**: `suggest_tax_loss_harvest(source="snaptrade")` -> only SnapTrade transactions
12. **Short positions skipped**: Verify SHORT direction lots are excluded in v1 (LONG only)
13. **Error case**: Invalid source -> `status: error`

## Estimated Complexity

**Medium** — comparable to `get_performance(mode="realized")`.

- **Core logic is straightforward**: FIFO matching is already done; this tool just reads `open_lots` and compares to current prices.
- **No new data fetching patterns**: Reuses transaction loading (data_fetcher), price fetching (ticker_resolver + FMP), and FX conversion (fmp/fx) — all well-tested paths.
- **Wash sale detection is simple**: Same-ticker scan within date window. No complex "substantially identical" matching.
- **Main work**: Building the output formatting (summary/full/report) and handling edge cases (multi-currency, options). Short lots deferred to v2.

Estimated implementation time: **3-4 hours** including tests.

Files changed: 5 (2 new + 3 modified).

---

*Created: 2026-02-07*
