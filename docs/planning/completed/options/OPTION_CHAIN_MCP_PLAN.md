# Option Chain Analysis MCP Tool

## Context

`options/chain_analysis.py` already has `analyze_chain()` which computes OI/volume by strike, put/call ratio, max pain, and optional strategy overlay. IBKR already has chain fetching (`ibkr/metadata.py`) and snapshot fetching (`ibkr/market_data.py`). But there's no MCP tool connecting these — a user can't ask "show me the AAPL options chain analysis for Jan 2025 expiry."

## Data Flow

```
User: symbol + expiry
  → IBKRClient.get_option_chain() → available strikes
  → IBKRClient.fetch_snapshot() → OI/volume/Greeks per strike (calls + puts)
  → analyze_chain() → OI concentration, put/call ratio, max pain
  → format response (summary/full/agent)
```

## Key Data Shape Bridging

IBKR `fetch_snapshot()` returns per-contract: `{bid, ask, volume, open_interest, delta, ...}`. The contract object has `strike` and `right` but these aren't in the snapshot dict. `analyze_chain()._normalize_snapshots()` expects `{strike, right, open_interest, volume}`. So the MCP tool must merge contract metadata into snapshot dicts before calling `analyze_chain()`.

For each strike, we fetch TWO contracts (call + put) to get both sides' OI/volume.

## Changes

### 1. `mcp_tools/chain_analysis.py` — NEW (~100 lines)

Main tool function:

```python
@handle_mcp_errors
def analyze_option_chain(
    symbol: str,
    expiry: str,
    strikes: Optional[list[float]] = None,    # Auto-detect from chain if None
    strike_count: int = 20,                    # Max strikes per side when auto-detecting
    exchange: str = "SMART",
    sec_type: str = "STK",                     # STK or FUT underlying
    format: Literal["full", "summary", "agent"] = "summary",
    output: Literal["inline", "file"] = "inline",
) -> dict:
```

**Logic:**
1. Create single `IBKRClient()` instance (shared for chain + snapshot calls)
2. `client.get_option_chain(symbol, sec_type, exchange)` → get available strikes for the expiry
3. **Validate**: If chain is empty (`chains == []`), raise `ValueError("no option chains available")`
4. **Validate**: If `expiry` not found in any chain's `expirations`, raise `ValueError(f"expiry {expiry} not available")`
5. If `strikes` not provided, auto-select strikes centered around ATM (use `strike_count` to limit — chains can have 100+ strikes)
6. Build `Option(symbol, expiry, strike, "C")` + `Option(symbol, expiry, strike, "P")` contracts for each strike
7. `client.fetch_snapshot(contracts)` → get OI/volume/Greeks
8. Merge strike + right into each snapshot dict → `strike_snapshots` list. **Filter out** snapshots with `"error"` key (partial failures are normal — IBKR may timeout on some contracts)
9. `analyze_chain({}, strike_snapshots)` → chain analysis result
10. Format response based on `format` param

**ATM strike selection**: Fetch underlying price via FMP (`fetch_fmp_quote_with_currency`). If FMP returns no price (e.g., futures symbols), fall back to IBKR snapshot of the underlying contract (`client.fetch_snapshot([underlying_contract])`). Find closest strike, take `strike_count // 2` above and below.

**Helper functions:**
- `_select_strikes(chain_data, expiry, underlying_price, strike_count)` — filter available strikes to reasonable range
- `_build_strike_snapshots(strikes, snapshots, contracts)` — merge contract metadata into snapshot dicts
- `_save_chain_analysis(result_dict)` — save full output to `logs/options/chain_*.json`
- `_build_agent_response(analysis, symbol, expiry, underlying_price, file_path)` — compose agent snapshot + flags

### 2. `core/chain_analysis_flags.py` — NEW (~60 lines)

Interpretive flags for agent format:

| Flag | Severity | Condition |
|------|----------|-----------|
| `fetch_error` | error | No chain data or all snapshots failed |
| `high_put_call_ratio` | warning | put/call ratio > 1.5 (bearish skew) |
| `low_put_call_ratio` | info | put/call ratio < 0.5 (bullish skew) |
| `max_pain_below_current` | info | max pain < underlying price (downward magnet) |
| `max_pain_above_current` | info | max pain > underlying price (upward magnet) |
| `concentrated_oi` | info | single strike has > 25% of total OI |
| `low_liquidity` | warning | total OI < 1000 or total volume < 100 |
| `near_expiry` | info | expiry is within 5 trading days (gamma risk, pin behavior) |
| `analysis_complete` | success | Chain analysis ran successfully |

### 3. `mcp_server.py` — Add tool registration

```python
from mcp_tools.chain_analysis import analyze_option_chain as _analyze_option_chain

@mcp.tool()
def analyze_option_chain(
    symbol: str,
    expiry: str,
    strikes: Optional[list[float]] = None,
    strike_count: int = 20,
    exchange: str = "SMART",
    sec_type: str = "STK",
    format: Literal["full", "summary", "agent"] = "summary",
    output: Literal["inline", "file"] = "inline",
) -> dict:
    """Analyze option chain OI/volume concentration, put/call ratio, and max pain.

    Fetches live chain data from IBKR Gateway and runs analytics.

    Args:
        symbol: Underlying ticker (e.g., "AAPL", "SPY")
        expiry: Expiration date in YYYYMMDD format (e.g., "20250117")
        strikes: Specific strikes to analyze. If omitted, auto-selects ~20 strikes around ATM.
        strike_count: Number of strikes to analyze when auto-selecting (default 20)
        exchange: IBKR exchange (default "SMART")
        sec_type: Underlying type — "STK" for equities, "FUT" for futures (default "STK")
        format: Response format — "summary" (default), "full" (all data), "agent" (flags + snapshot)
        output: "inline" (default) or "file" (save full analysis to disk)
    """
    return _analyze_option_chain(
        symbol=symbol, expiry=expiry, strikes=strikes, strike_count=strike_count,
        exchange=exchange, sec_type=sec_type, format=format, output=output,
    )
```

### 4. `tests/options/test_chain_analysis.py` — NEW (~120 lines)

Unit tests with mocked IBKR:

- `test_analyze_chain_summary_success` — mock chain + snapshots, verify summary shape
- `test_analyze_chain_agent_format` — verify snapshot + flags shape
- `test_analyze_chain_file_output` — verify file_path returned
- `test_auto_strike_selection` — verify ATM centering logic
- `test_all_snapshots_error` — verify error handling when IBKR returns all timeouts
- `test_high_put_call_ratio_flag` — verify bearish skew flag
- `test_low_liquidity_flag` — verify low OI warning
- `test_invalid_expiry_not_in_chain` — verify error when expiry doesn't exist
- `test_partial_snapshot_errors` — some strikes return `{"error": "timeout"}`, verify tool still produces results from successful ones
- `test_empty_chain` — `get_option_chain()` returns empty chains, verify descriptive error

### 5. `tests/options/test_chain_analysis_flags.py` — NEW (~60 lines)

Unit tests for flag generation (pure dict input, no IBKR mocking needed).

## Response Shapes

**Summary format:**
```json
{
  "status": "success",
  "symbol": "AAPL",
  "expiry": "20250117",
  "underlying_price": 195.50,
  "strike_count": 20,
  "put_call_ratio": 1.23,
  "max_pain": 190.0,
  "total_call_oi": 45000,
  "total_put_oi": 55350,
  "total_call_volume": 6200,
  "total_put_volume": 6300,
  "total_volume": 12500,
  "top_oi_strikes": [190.0, 195.0, 200.0]
}
```

**Agent snapshot:**
```json
{
  "symbol": "AAPL",
  "expiry": "20250117",
  "underlying_price": 195.50,
  "verdict": "AAPL 20250117: P/C ratio 1.23, max pain $190, 20 strikes analyzed",
  "put_call_ratio": 1.23,
  "max_pain": 190.0,
  "max_pain_vs_current_pct": -2.81,
  "total_call_oi": 45000,
  "total_put_oi": 55350,
  "total_call_volume": 6200,
  "total_put_volume": 6300,
  "total_volume": 12500,
  "strike_count": 20,
  "top_oi_strikes": [190.0, 195.0, 200.0],
  "highest_oi_strike": 190.0,
  "highest_oi_concentration_pct": 18.5
}
```

**Full format** — includes everything above plus `oi_by_strike` and `volume_by_strike` dicts (per-strike breakdown).

## Files Modified

| File | Action |
|------|--------|
| `mcp_tools/chain_analysis.py` | NEW — tool implementation (~100 lines) |
| `core/chain_analysis_flags.py` | NEW — agent flags (~60 lines) |
| `mcp_server.py` | Add import + `@mcp.tool()` registration |
| `tests/options/test_chain_analysis.py` | NEW — tool tests (~120 lines) |
| `tests/options/test_chain_analysis_flags.py` | NEW — flag tests (~60 lines) |

## Existing Code Reused

- `options/chain_analysis.py` → `analyze_chain()` — core analytics (no changes needed)
- `ibkr/client.py` → `IBKRClient.get_option_chain()`, `IBKRClient.fetch_snapshot()` — IBKR data
- `mcp_tools/common.py` → `@handle_mcp_errors` — error handling decorator
- `utils/ticker_resolver.py` → `fetch_fmp_quote_with_currency()` — underlying price for ATM detection
- `core/option_strategy_flags.py` → `_sort_flags()` pattern — flag severity sorting

## Verification

```bash
# Unit tests
pytest tests/options/test_chain_analysis.py tests/options/test_chain_analysis_flags.py -v

# All options tests still pass
pytest tests/options/ -v

# Broader test suite
pytest tests/ -x -q --timeout=30 -k "not slow"

# Import check
python3 -c "from mcp_tools.chain_analysis import analyze_option_chain; print('OK')"

# Live test (requires IBKR Gateway running)
python3 -c "
from mcp_tools.chain_analysis import analyze_option_chain
result = analyze_option_chain(symbol='AAPL', expiry='20250620', format='summary')
print(result)
"
```
