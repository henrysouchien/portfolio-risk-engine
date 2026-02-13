# Technical Analysis MCP Tool - Implementation Plan

> **Status:** PLANNED

## Overview

Expose a composite technical analysis view via a single MCP tool (`get_technical_analysis`) on the `portfolio-mcp` server. The tool fetches multiple technical indicators from FMP in parallel, computes derived indicators (MACD, Bollinger Bands), and returns either a current-signal summary or full time-series data.

This is a standalone ticker-based tool (like `analyze_stock`) -- no portfolio context, no `PositionService`, no `_resolve_user_id`.

## Use Cases & Example Queries

This tool answers questions about price trends, momentum, overbought/oversold conditions, and timing signals. Example natural language queries:

- **"Is AAPL overbought right now?"** -- `get_technical_analysis(symbol="AAPL")` returns RSI, Williams %R, and Bollinger Band signals indicating overbought/oversold status
- **"What are the technicals on TSLA?"** -- `get_technical_analysis(symbol="TSLA")` provides the full composite signal with trend, momentum, and volatility analysis
- **"Is this a good entry point for MSFT?"** -- `get_technical_analysis(symbol="MSFT")` shows support/resistance levels, moving average alignment, and the overall buy/sell signal
- **"Show me RSI and moving averages for AMZN"** -- `get_technical_analysis(symbol="AMZN", indicators=["rsi", "sma"])` returns only the requested indicator subset
- **"What's the hourly trend on SPY?"** -- `get_technical_analysis(symbol="SPY", timeframe="1hour")` provides intraday technical signals

### Tool Chaining Example

A comprehensive question like **"Should I buy NVDA?"** would chain multiple tools for a full picture:

1. `analyze_stock(ticker="NVDA")` -- fundamentals, risk metrics, and factor exposures
2. `get_technical_analysis(symbol="NVDA")` -- timing signals (trend direction, RSI, MACD, support/resistance)
3. `get_news(symbols="NVDA")` -- recent catalysts and sentiment from news headlines
4. `compare_peers(symbol="NVDA")` -- relative valuation against peers (P/E, margins, growth)

The agent synthesizes fundamental quality, technical timing, news catalysts, and relative value into a holistic buy/hold/sell assessment.

---

## FMP Endpoints Required

Six new endpoint registrations in `fmp/registry.py`, all in a new `"technical"` category:

| Registry Name | FMP Path | Params | Cache Strategy |
|---------------|----------|--------|----------------|
| `ta_sma` | `/stable/technical-indicators/sma` | symbol, periodLength, timeframe, from, to | TTL 4h |
| `ta_ema` | `/stable/technical-indicators/ema` | symbol, periodLength, timeframe, from, to | TTL 4h |
| `ta_rsi` | `/stable/technical-indicators/rsi` | symbol, periodLength, timeframe, from, to | TTL 4h |
| `ta_adx` | `/stable/technical-indicators/adx` | symbol, periodLength, timeframe, from, to | TTL 4h |
| `ta_williams` | `/stable/technical-indicators/williams` | symbol, periodLength, timeframe, from, to | TTL 4h |
| `ta_stddev` | `/stable/technical-indicators/standarddeviation` | symbol, periodLength, timeframe, from, to | TTL 4h |

**Why TTL 4h:** Technical indicators on daily timeframe change once per day, but intraday timeframes update more frequently. 4 hours balances freshness with API rate limits. The `use_cache` param lets callers bypass when needed.

**Common params for all six:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `symbol` | STRING | Yes | - | Stock symbol |
| `periodLength` | INTEGER | No | 14 | Indicator period length |
| `timeframe` | ENUM | No | `"1day"` | Candle timeframe (1min, 5min, 15min, 30min, 1hour, 4hour, 1day) |
| `from` | DATE | No | - | Start date (YYYY-MM-DD) |
| `to` | DATE | No | - | End date (YYYY-MM-DD) |

## Tool

### `get_technical_analysis`

**Purpose:** Composite technical analysis for a single ticker -- trend, momentum, volatility, and support/resistance signals.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | `str` | (required) | Stock ticker to analyze (e.g., "AAPL", "MSFT") |
| `timeframe` | `Literal["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"]` | `"1day"` | Candle timeframe |
| `indicators` | `Optional[list[str]]` | `None` | Subset of indicators to include. Options: `"sma"`, `"ema"`, `"rsi"`, `"adx"`, `"williams"`, `"macd"`, `"bollinger"`. Default (None): all |
| `period_overrides` | `Optional[dict]` | `None` | Override default period lengths. Keys: `"sma_periods"`, `"ema_periods"`, `"rsi_period"`, `"adx_period"`, `"williams_period"`, `"stddev_period"`. Example: `{"sma_periods": [10, 50, 200], "rsi_period": 21}` |
| `format` | `Literal["full", "summary"]` | `"summary"` | Output format |
| `use_cache` | `bool` | `True` | Use cached FMP data |

**Default period config (used when no overrides):**
```python
DEFAULT_PERIODS = {
    "sma_periods": [20, 50, 200],       # Short, medium, long-term trend
    "ema_periods": [12, 26],             # MACD inputs
    "rsi_period": 14,                    # Standard RSI
    "adx_period": 14,                    # Standard ADX
    "williams_period": 14,              # Standard Williams %R
    "stddev_period": 20,                # Bollinger Band volatility (matches SMA 20)
}
```

## Data Flow

### Step 1: Determine Required FMP Fetches

Based on `indicators` param (or all if None), build a list of `(endpoint_name, periodLength)` tuples:

```python
# If indicators=None or "sma" in indicators:
fetches += [("ta_sma", 20), ("ta_sma", 50), ("ta_sma", 200)]

# If indicators=None or "ema" in indicators or "macd" in indicators:
fetches += [("ta_ema", 12), ("ta_ema", 26)]

# If indicators=None or "macd" in indicators:
#   Also need EMA(9) of MACD line -- computed post-hoc, not a separate FMP call

# If indicators=None or "rsi" in indicators:
fetches += [("ta_rsi", 14)]

# If indicators=None or "adx" in indicators:
fetches += [("ta_adx", 14)]

# If indicators=None or "williams" in indicators:
fetches += [("ta_williams", 14)]

# If indicators=None or "bollinger" in indicators:
fetches += [("ta_stddev", 20)]
#   Also needs SMA(20) -- add to SMA fetches if not already present
```

### Step 2: Parallel Fetch via ThreadPoolExecutor

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from fmp.client import FMPClient

fmp = FMPClient()

def _fetch_indicator(endpoint_name: str, symbol: str, period: int, timeframe: str) -> tuple[str, int, pd.DataFrame]:
    """Fetch one indicator. Returns (endpoint_name, period, dataframe)."""
    df = fmp.fetch(endpoint_name, symbol=symbol, periodLength=period, timeframe=timeframe, use_cache=use_cache)
    return (endpoint_name, period, df)

results = {}
errors = {}

with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {
        executor.submit(_fetch_indicator, ep, symbol, period, timeframe): (ep, period)
        for ep, period in fetches
    }
    for future in as_completed(futures):
        ep, period = futures[future]
        try:
            key = f"{ep}_{period}"
            _, _, df = future.result()
            results[key] = df
        except Exception as e:
            errors[f"{ep}_{period}"] = str(e)
```

**Why parallel:** Default config requires up to 9 separate FMP calls (3 SMA + 2 EMA + RSI + ADX + Williams + StdDev). Sequential fetching would take 9x the latency. With ThreadPoolExecutor(max_workers=6), we respect reasonable concurrency limits while cutting wall-clock time to roughly 2 round-trips.

### Step 3: Compute Derived Indicators

**MACD** (from EMA data):
```python
# MACD line = EMA(12) close - EMA(26) close
# Signal line = EMA(9) of MACD line (computed via pandas ewm)
# Histogram = MACD line - Signal line

ema12 = results["ta_ema_12"].set_index("date")["ema"]
ema26 = results["ta_ema_26"].set_index("date")["ema"]
macd_line = ema12 - ema26
signal_line = macd_line.ewm(span=9, adjust=False).mean()
histogram = macd_line - signal_line
```

**Bollinger Bands** (from SMA + StdDev data):
```python
# Upper band = SMA(20) + 2 * StdDev(20)
# Lower band = SMA(20) - 2 * StdDev(20)
# %B = (Close - Lower) / (Upper - Lower)
# Bandwidth = (Upper - Lower) / SMA(20)

sma20 = results["ta_sma_20"].set_index("date")["sma"]
stddev20 = results["ta_stddev_20"].set_index("date")["standardDeviation"]
upper_band = sma20 + 2 * stddev20
lower_band = sma20 - 2 * stddev20
close = results["ta_sma_20"].set_index("date")["close"]  # SMA response includes close
pct_b = (close - lower_band) / (upper_band - lower_band)
bandwidth = (upper_band - lower_band) / sma20
```

### Step 4: Build Signal Interpretation (Summary Format)

Extract the most recent data point from each indicator and apply interpretation rules:

#### Trend Direction (from SMA crossovers)
```python
latest_close = ...  # from most recent SMA data point
sma20_val = latest SMA(20)
sma50_val = latest SMA(50)
sma200_val = latest SMA(200)

# Primary trend
if latest_close > sma200_val:
    primary_trend = "bullish"  # Price above 200-day
elif latest_close < sma200_val:
    primary_trend = "bearish"  # Price below 200-day

# Trend alignment
if sma20_val > sma50_val > sma200_val:
    trend_alignment = "strongly_bullish"  # All MAs in bullish order
elif sma20_val < sma50_val < sma200_val:
    trend_alignment = "strongly_bearish"  # All MAs in bearish order
else:
    trend_alignment = "mixed"  # Transitioning

# Golden/Death cross detection
if sma50_val > sma200_val:
    ma_cross = "golden_cross"  # 50-day above 200-day
else:
    ma_cross = "death_cross"   # 50-day below 200-day
```

#### Momentum (from RSI + Williams %R)
```python
rsi_val = latest RSI(14)

if rsi_val >= 70:
    rsi_signal = "overbought"
elif rsi_val >= 60:
    rsi_signal = "bullish"
elif rsi_val <= 30:
    rsi_signal = "oversold"
elif rsi_val <= 40:
    rsi_signal = "bearish"
else:
    rsi_signal = "neutral"

williams_val = latest Williams(14)  # Range: -100 to 0

if williams_val >= -20:
    williams_signal = "overbought"
elif williams_val <= -80:
    williams_signal = "oversold"
else:
    williams_signal = "neutral"
```

#### Trend Strength (from ADX)
```python
adx_val = latest ADX(14)

if adx_val >= 50:
    trend_strength = "very_strong"
elif adx_val >= 25:
    trend_strength = "strong"
elif adx_val >= 20:
    trend_strength = "developing"
else:
    trend_strength = "weak"  # No clear trend / range-bound
```

#### MACD Signal
```python
macd_val = latest MACD line
signal_val = latest signal line
histogram_val = latest histogram

if macd_val > signal_val and histogram_val > 0:
    macd_signal = "bullish"
elif macd_val < signal_val and histogram_val < 0:
    macd_signal = "bearish"
else:
    macd_signal = "neutral"  # Crossover in progress

# Detect divergence direction
if histogram_val > prev_histogram_val:
    macd_momentum = "increasing"
else:
    macd_momentum = "decreasing"
```

#### Support/Resistance (from Bollinger Bands + SMAs)
```python
support_levels = sorted([
    ("sma_20", sma20_val),
    ("sma_50", sma50_val),
    ("sma_200", sma200_val),
    ("bollinger_lower", lower_band_val),
], key=lambda x: x[1])

resistance_levels = [("bollinger_upper", upper_band_val)]

# Filter: only levels below current price are support, above are resistance
support = [{"level": name, "price": round(val, 2)}
           for name, val in support_levels if val < latest_close]
resistance = [{"level": name, "price": round(val, 2)}
              for name, val in support_levels + resistance_levels if val > latest_close]

# Bollinger position
if pct_b_val > 1.0:
    bollinger_signal = "above_upper_band"  # Overbought / breakout
elif pct_b_val < 0.0:
    bollinger_signal = "below_lower_band"  # Oversold / breakdown
elif pct_b_val > 0.8:
    bollinger_signal = "near_upper_band"
elif pct_b_val < 0.2:
    bollinger_signal = "near_lower_band"
else:
    bollinger_signal = "mid_band"

volatility_signal = "high" if bandwidth_val > 0.10 else "normal" if bandwidth_val > 0.04 else "low"  # Squeeze detection
```

#### Composite Signal
```python
# Simple scoring: each indicator votes bullish (+1) / bearish (-1) / neutral (0)
score = 0
score += 1 if primary_trend == "bullish" else -1
score += 1 if rsi_signal in ("bullish", "oversold") else (-1 if rsi_signal in ("bearish", "overbought") else 0)
score += 1 if macd_signal == "bullish" else (-1 if macd_signal == "bearish" else 0)
score += 1 if williams_signal == "oversold" else (-1 if williams_signal == "overbought" else 0)

if score >= 3:
    composite = "strong_buy"
elif score >= 1:
    composite = "buy"
elif score <= -3:
    composite = "strong_sell"
elif score <= -1:
    composite = "sell"
else:
    composite = "neutral"
```

## Output Structures

### Summary Format

```python
{
    "status": "success",
    "symbol": "AAPL",
    "timeframe": "1day",
    "as_of": "2026-02-07",       # Date of most recent data point
    "price": 234.56,              # Latest close

    "composite_signal": "buy",    # strong_buy / buy / neutral / sell / strong_sell
    "signal_score": 2,            # Raw score (-4 to +4)

    "trend": {
        "primary": "bullish",            # bullish / bearish
        "alignment": "strongly_bullish", # strongly_bullish / mixed / strongly_bearish
        "ma_cross": "golden_cross",      # golden_cross / death_cross
        "adx_strength": "strong",        # weak / developing / strong / very_strong
        "adx_value": 32.5
    },

    "momentum": {
        "rsi": {"value": 62.3, "signal": "bullish"},       # overbought / bullish / neutral / bearish / oversold
        "williams": {"value": -25.4, "signal": "neutral"},  # overbought / neutral / oversold
        "macd": {
            "signal": "bullish",       # bullish / bearish / neutral
            "momentum": "increasing",  # increasing / decreasing
            "macd_line": 2.45,
            "signal_line": 1.89,
            "histogram": 0.56
        }
    },

    "volatility": {
        "bollinger": {
            "signal": "mid_band",   # above_upper_band / near_upper_band / mid_band / near_lower_band / below_lower_band
            "pct_b": 0.65,
            "bandwidth": 0.062,
            "squeeze": false,       # True when bandwidth is very low (< 0.04)
            "upper": 240.12,
            "lower": 228.88
        },
        "std_dev": 2.81
    },

    "moving_averages": {
        "sma_20": 232.10,
        "sma_50": 228.45,
        "sma_200": 215.30,
        "ema_12": 233.80,
        "ema_26": 231.35
    },

    "support_resistance": {
        "support": [
            {"level": "sma_20", "price": 232.10},
            {"level": "sma_50", "price": 228.45}
        ],
        "resistance": [
            {"level": "bollinger_upper", "price": 240.12}
        ]
    },

    "indicators_failed": [],     # List of indicators that failed to fetch (partial results)
    "indicators_included": ["sma", "ema", "rsi", "adx", "williams", "macd", "bollinger"]
}
```

### Full Format

```python
{
    "status": "success",
    "symbol": "AAPL",
    "timeframe": "1day",
    "as_of": "2026-02-07",
    "price": 234.56,

    # Everything from summary:
    "composite_signal": "buy",
    "signal_score": 2,
    "trend": {...},
    "momentum": {...},
    "volatility": {...},
    "moving_averages": {...},
    "support_resistance": {...},

    # Plus full time series data:
    "time_series": {
        "sma_20": [{"date": "2026-02-07", "close": 234.56, "sma": 232.10}, ...],
        "sma_50": [...],
        "sma_200": [...],
        "ema_12": [...],
        "ema_26": [...],
        "rsi_14": [{"date": "2026-02-07", "close": 234.56, "rsi": 62.3}, ...],
        "adx_14": [{"date": "2026-02-07", "close": 234.56, "adx": 32.5}, ...],
        "williams_14": [...],
        "macd": [{"date": "2026-02-07", "macd_line": 2.45, "signal_line": 1.89, "histogram": 0.56}, ...],
        "bollinger": [{"date": "2026-02-07", "close": 234.56, "upper": 240.12, "sma": 232.10, "lower": 228.88, "pct_b": 0.65, "bandwidth": 0.062}, ...]
    },

    "indicators_failed": [],
    "indicators_included": ["sma", "ema", "rsi", "adx", "williams", "macd", "bollinger"],
    "fetch_time_ms": 1234       # Total wall-clock time for all FMP fetches
}
```

## Error Handling

### Partial Failure Strategy

Individual indicator failures should NOT fail the entire tool. The tool produces a best-effort composite from whatever indicators succeed.

```python
# After parallel fetch:
if errors:
    # Some indicators failed -- continue with what we have
    # Track which high-level indicators are affected
    failed_indicators = set()
    for key, err_msg in errors.items():
        if key.startswith("ta_sma"):
            failed_indicators.add("sma")
        elif key.startswith("ta_ema"):
            failed_indicators.add("ema")
            failed_indicators.add("macd")  # MACD depends on EMA
        elif key.startswith("ta_rsi"):
            failed_indicators.add("rsi")
        elif key.startswith("ta_adx"):
            failed_indicators.add("adx")
        elif key.startswith("ta_williams"):
            failed_indicators.add("williams")
        elif key.startswith("ta_stddev"):
            failed_indicators.add("bollinger")  # Bollinger depends on StdDev

# Compute derived indicators only if dependencies are met:
can_compute_macd = "ta_ema_12" in results and "ta_ema_26" in results
can_compute_bollinger = "ta_sma_20" in results and "ta_stddev_20" in results

# Signal interpretation skips missing indicators (neutral vote for missing)
# Composite score adjusted for number of available indicators
```

### Total Failure

If ALL indicator fetches fail (e.g., invalid symbol, API down), return a standard error:

```python
if not results:
    return {
        "status": "error",
        "error": f"All indicator fetches failed for {symbol}. Errors: {errors}"
    }
```

### Invalid Symbol

FMP returns empty data for unknown symbols. The first fetch to fail will raise `FMPEmptyResponseError`. With partial failure, the tool still attempts all fetches -- if all fail with empty response, the total failure path above handles it.

### Invalid Timeframe

The `timeframe` param is constrained via `Literal` type in the function signature. Invalid values are rejected before any FMP calls.

## Files to Create/Modify

### New Files

1. **`mcp_tools/technical.py`** -- Tool implementation (`get_technical_analysis`) plus helper functions for parallel fetching, derived indicator computation, and signal interpretation.

### Modified Files

2. **`fmp/registry.py`** -- 6 new endpoint registrations (`ta_sma`, `ta_ema`, `ta_rsi`, `ta_adx`, `ta_williams`, `ta_stddev`)
3. **`mcp_server.py`** -- Import + 1 `@mcp.tool()` registration
4. **`mcp_tools/__init__.py`** -- Import + export
5. **`mcp_tools/README.md`** -- Document new tool

## Implementation Details

### `fmp/registry.py` additions

```python
# --- Technical Indicators ---
# Intraday data changes frequently; use TTL-based caching

_TIMEFRAME_VALUES = ["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"]

for _ta_name, _ta_path, _ta_desc in [
    ("ta_sma", "/technical-indicators/sma", "Simple Moving Average"),
    ("ta_ema", "/technical-indicators/ema", "Exponential Moving Average"),
    ("ta_rsi", "/technical-indicators/rsi", "Relative Strength Index (0-100)"),
    ("ta_adx", "/technical-indicators/adx", "Average Directional Index (trend strength)"),
    ("ta_williams", "/technical-indicators/williams", "Williams %R (-100 to 0)"),
    ("ta_stddev", "/technical-indicators/standarddeviation", "Standard Deviation (volatility)"),
]:
    register_endpoint(
        FMPEndpoint(
            name=_ta_name,
            path=_ta_path,
            description=_ta_desc,
            fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#technical-indicators",
            category="technical",
            api_version="stable",
            params=[
                EndpointParam("symbol", ParamType.STRING, required=True, description="Stock symbol"),
                EndpointParam("periodLength", ParamType.INTEGER, default=14, description="Indicator period"),
                EndpointParam(
                    "timeframe",
                    ParamType.ENUM,
                    default="1day",
                    enum_values=_TIMEFRAME_VALUES,
                    description="Candle timeframe",
                ),
                EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
                EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
            ],
            cache_dir="cache/technical",
            cache_refresh=CacheRefresh.TTL,
            cache_ttl_hours=4,
        )
    )
```

**Note:** Loop registration keeps it DRY -- all 6 endpoints share the same parameter structure. The loop variables are prefixed with `_` to avoid polluting the module namespace.

### `mcp_tools/technical.py`

```python
"""
MCP Tool: get_technical_analysis

Composite technical analysis for a single stock: trend direction,
momentum signals, volatility, and support/resistance levels.

Usage (from Claude):
    "Technical analysis for AAPL"
    "Is TSLA overbought?"
    "What's the trend for MSFT?"
    "Show me MACD and RSI for NVDA"

Architecture note:
- Standalone ticker tool (no portfolio loading required)
- Parallel-fetches multiple FMP technical indicator endpoints
- Computes derived indicators (MACD, Bollinger Bands) from raw data
- Interprets signals into actionable summary
"""

import sys
import time
from typing import Optional, Literal
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from fmp.client import FMPClient


# Default period configurations
DEFAULT_PERIODS = {
    "sma_periods": [20, 50, 200],
    "ema_periods": [12, 26],
    "rsi_period": 14,
    "adx_period": 14,
    "williams_period": 14,
    "stddev_period": 20,
}

# Valid indicator names for the `indicators` parameter
VALID_INDICATORS = {"sma", "ema", "rsi", "adx", "williams", "macd", "bollinger"}


def get_technical_analysis(
    symbol: str,
    timeframe: Literal["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"] = "1day",
    indicators: Optional[list[str]] = None,
    period_overrides: Optional[dict] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get composite technical analysis for a single stock.

    Args:
        symbol: Stock ticker (e.g., "AAPL", "MSFT").
        timeframe: Candle timeframe (default "1day").
        indicators: Subset of indicators to include. Options: "sma", "ema",
            "rsi", "adx", "williams", "macd", "bollinger". Default: all.
        period_overrides: Override default period lengths. Keys: sma_periods,
            ema_periods, rsi_period, adx_period, williams_period, stddev_period.
        format: "summary" (signals + current values) or "full" (+ time series).
        use_cache: Use cached FMP data (default True).

    Returns:
        dict with status field ("success" or "error")
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # 1. Validate indicators
        requested = set(indicators) if indicators else VALID_INDICATORS
        invalid = requested - VALID_INDICATORS
        if invalid:
            return {
                "status": "error",
                "error": f"Invalid indicators: {sorted(invalid)}. "
                         f"Valid options: {sorted(VALID_INDICATORS)}"
            }

        # 2. Merge period config
        periods = {**DEFAULT_PERIODS}
        if period_overrides:
            periods.update(period_overrides)

        # 3. Build fetch list
        fetches = _build_fetch_list(requested, periods)

        # 4. Parallel fetch
        start_time = time.time()
        results, errors = _parallel_fetch(fetches, symbol, timeframe, use_cache)
        fetch_time_ms = int((time.time() - start_time) * 1000)

        # 5. Check for total failure
        if not results:
            return {
                "status": "error",
                "error": f"All indicator fetches failed for '{symbol}'. "
                         f"Errors: {errors}"
            }

        # 6. Compute derived indicators
        derived = _compute_derived(results, requested, periods)

        # 7. Build signal interpretation
        signals = _interpret_signals(results, derived, periods)

        # 8. Determine which high-level indicators we actually have
        included, failed = _categorize_results(results, errors, requested)

        # 9. Format response
        response = {
            "status": "success",
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            **signals,
            "indicators_included": sorted(included),
            "indicators_failed": sorted(failed),
        }

        if format == "full":
            response["time_series"] = _build_time_series(results, derived, periods)
            response["fetch_time_ms"] = fetch_time_ms

        return response

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved


def _build_fetch_list(requested, periods):
    """Build list of (endpoint_name, periodLength) tuples for FMP fetches."""
    ...

def _parallel_fetch(fetches, symbol, timeframe, use_cache):
    """Fetch all indicators in parallel via ThreadPoolExecutor. Returns (results, errors)."""
    ...

def _compute_derived(results, requested, periods):
    """Compute MACD and Bollinger Bands from raw indicator data."""
    ...

def _interpret_signals(results, derived, periods):
    """Extract latest values and build signal interpretation dict."""
    ...

def _categorize_results(results, errors, requested):
    """Determine which high-level indicators succeeded/failed. Returns (included, failed) sets."""
    ...

def _build_time_series(results, derived, periods):
    """Build time_series dict for full format output."""
    ...
```

### `mcp_server.py` additions

```python
# Add import (at top, within stdout redirect block)
from mcp_tools.technical import get_technical_analysis as _get_technical_analysis

# Add tool registration (after get_factor_recommendations)

@mcp.tool()
def get_technical_analysis(
    symbol: str,
    timeframe: Literal["1min", "5min", "15min", "30min", "1hour", "4hour", "1day"] = "1day",
    indicators: Optional[list[str]] = None,
    period_overrides: Optional[dict] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get composite technical analysis for a single stock or ETF.

    Fetches multiple technical indicators and provides trend direction,
    momentum signals, volatility analysis, and support/resistance levels
    with an overall buy/sell signal.

    Args:
        symbol: Stock or ETF symbol to analyze (e.g., "AAPL", "SPY").
        timeframe: Candle timeframe for analysis:
            - "1day": Daily (default, most common)
            - "1hour", "4hour": Intraday swing
            - "1min", "5min", "15min", "30min": Intraday scalping
        indicators: Optional subset of indicators to include. Options:
            "sma", "ema", "rsi", "adx", "williams", "macd", "bollinger".
            Default: all indicators.
        period_overrides: Override default period lengths. Example:
            {"sma_periods": [10, 50, 200], "rsi_period": 21}
        format: Output format:
            - "summary": Current signals and key values
            - "full": Signals plus complete time series data
        use_cache: Use cached indicator data when available (default: True).

    Returns:
        Technical analysis data with status field ("success" or "error").

    Examples:
        "Technical analysis for AAPL" -> get_technical_analysis(symbol="AAPL")
        "Is TSLA overbought?" -> get_technical_analysis(symbol="TSLA")
        "Show me MACD for NVDA" -> get_technical_analysis(symbol="NVDA", indicators=["macd"])
        "Hourly technicals for SPY" -> get_technical_analysis(symbol="SPY", timeframe="1hour")
        "Full technical data for MSFT" -> get_technical_analysis(symbol="MSFT", format="full")
    """
    return _get_technical_analysis(
        symbol=symbol,
        timeframe=timeframe,
        indicators=indicators,
        period_overrides=period_overrides,
        format=format,
        use_cache=use_cache,
    )
```

### `mcp_tools/__init__.py` additions

```python
# Add import
from mcp_tools.technical import get_technical_analysis

# Add to __all__
"get_technical_analysis",
```

### `mcp_tools/README.md` updates

- Add `get_technical_analysis` to tool list with parameters and examples
- Add `technical.py` to file organization listing

## Edge Cases

1. **Indicator subset with MACD but no EMA:** If `indicators=["macd"]`, the tool implicitly fetches EMA(12) and EMA(26) since MACD is derived from them. The `_build_fetch_list()` function handles these dependencies.

2. **Indicator subset with Bollinger but no SMA:** If `indicators=["bollinger"]`, the tool implicitly fetches SMA(20) and StdDev(20). These are added to the fetch list regardless of whether `"sma"` is in the requested set.

3. **Period override conflicts:** If `period_overrides={"sma_periods": [10, 50]}` (no 200-day), the trend interpretation adapts -- uses whatever SMA periods are available. The 200-day check for primary trend falls back to the longest available SMA.

4. **Intraday timeframes:** For timeframes < 1day, the `from`/`to` date params on FMP endpoints may return different amounts of data. The tool does not set these by default (lets FMP return its default window), but they're available as future enhancement.

5. **Rate limiting:** With up to 9 concurrent FMP requests, rate limiting is possible. The `FMPClient` already raises `FMPRateLimitError` on 429 responses. The partial failure strategy handles individual rate-limited fetches gracefully.

6. **Empty DataFrame from FMP:** Some tickers (OTC, very new IPOs) may not have enough history for long-period indicators (e.g., SMA 200). The indicator is treated as failed for that period, and the signal interpretation skips it.

## Verification Steps

1. **Import test**: `from mcp_tools.technical import get_technical_analysis` -- no import errors
2. **Endpoint registration**: `from fmp.registry import get_endpoint; assert get_endpoint("ta_sma") is not None`
3. **Summary format (all indicators)**: `get_technical_analysis(symbol="AAPL")` -- status: success, composite_signal present
4. **Full format**: `get_technical_analysis(symbol="AAPL", format="full")` -- time_series dict with all indicator data
5. **Indicator subset**: `get_technical_analysis(symbol="AAPL", indicators=["rsi", "macd"])` -- only rsi, ema, macd in results
6. **Invalid indicator**: `get_technical_analysis(symbol="AAPL", indicators=["invalid"])` -- status: error
7. **Invalid symbol**: `get_technical_analysis(symbol="ZZZZZZZ")` -- status: error (all fetches fail)
8. **Period overrides**: `get_technical_analysis(symbol="AAPL", period_overrides={"sma_periods": [10, 50]})` -- uses custom SMA periods
9. **Intraday timeframe**: `get_technical_analysis(symbol="AAPL", timeframe="1hour")` -- works with hourly data
10. **Partial failure**: If one indicator endpoint is temporarily down, others still produce results

## Patterns Followed

| Pattern | Implementation |
|---------|---------------|
| stdout redirection | `sys.stdout = sys.stderr` in try/finally |
| Error handling | `try/except -> {"status": "error", "error": str(e)}` |
| Format switching | summary/full consistent structure |
| Tool registration | `@mcp.tool()` in `mcp_server.py` with full docstrings |
| Exports | `mcp_tools/__init__.py` imports + `__all__` |
| No user context | Standalone ticker tool (like `analyze_stock`) |
| FMP client usage | `FMPClient().fetch(endpoint_name, ...)` with registered endpoints |
| Caching | TTL-based (4h) via endpoint config + `use_cache` param passthrough |

## Estimated Complexity

| Component | Effort | Notes |
|-----------|--------|-------|
| FMP endpoint registrations | Small | 6 registrations via loop -- minimal code |
| Parallel fetch logic | Small | ThreadPoolExecutor is standard pattern |
| Derived indicators (MACD, Bollinger) | Medium | Pandas math, need to align dates between DataFrames |
| Signal interpretation | Medium | Rule-based logic with many branches |
| Summary output formatting | Small | Dict assembly from computed values |
| Full output (time series) | Small | DataFrame to dict conversion |
| MCP registration boilerplate | Small | Standard pattern, 1 tool |
| Testing / verification | Medium | Need to verify FMP response shapes, edge cases |
| **Total** | **~3-4 hours** | Bulk of work is signal interpretation logic |

---

*Created: 2026-02-07*
