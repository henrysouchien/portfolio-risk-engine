# Portfolio Dividend Yield Implementation Plan

## Overview

This document outlines the implementation plan for adding portfolio-level dividend yield calculation to the risk analysis system. The feature will integrate with existing FMP API infrastructure and follow established patterns for data fetching, caching, and performance metric calculation.

## Current State Analysis

### What Exists
- ✅ **Total Return Infrastructure**: `fetch_monthly_total_return_price()` captures dividend reinvestment
- ✅ **FMP API Integration**: Established patterns in `data_loader.py` with caching and error handling
- ✅ **Performance Metrics Engine**: `calculate_portfolio_performance_metrics()` framework
- ✅ **Portfolio Weight System**: Normalized portfolio weights with proper asset allocation

### What's Missing
- ❌ **Individual Stock Dividend Data**: No dividend yield fetching from FMP
- ❌ **Portfolio Dividend Aggregation**: No weighted portfolio dividend yield calculation
- ❌ **Dividend Performance Integration**: No dividend metrics in performance analysis

## FMP Dividend Endpoint Analysis

**Endpoint**: `https://financialmodelingprep.com/stable/dividends?symbol={TICKER}&apikey={KEY}`

**Data Structure**:
```json
{
  "symbol": "AAPL",
  "date": "2025-08-11",
  "recordDate": "2025-08-11", 
  "paymentDate": "2025-08-14",
  "declarationDate": "2025-07-31",
  "adjDividend": 0.26,          // Adjusted dividend amount
  "dividend": 0.26,             // Raw dividend amount  
  "yield": 0.44898318513953694, // Dividend yield % at payment date
  "frequency": "Quarterly"      // Payment frequency
}
```

**Key Fields for Portfolio Calculation**:
- `adjDividend`: Dividend amount (split/merger adjusted)
- `yield`: Instantaneous dividend yield at payment date
- `date`: Ex-dividend date for timing
- `frequency`: Payment frequency (Quarterly, Annual, etc.)

## Implementation Architecture

**Decision**: Using **Current Yield Method Only** for simplicity and intuitive understanding.

### 1. Data Layer (`data_loader.py`)

**New Functions**:

### `fetch_dividend_history()` - Full Implementation
```python
@log_error_handling("high")
def fetch_dividend_history(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None
) -> pd.DataFrame:
    """
    Fetch dividend history for a ticker from FMP.
    
    Args:
        ticker (str): Stock or ETF symbol.
        start_date (str|datetime, optional): Earliest date (inclusive).
        end_date (str|datetime, optional): Latest date (inclusive).
    
    Returns:
        pd.DataFrame: Dividend history with columns: adjDividend, yield, frequency
                     Indexed by ex-dividend date.
    """
    
    # LOGGING: Add FMP API data fetch request logging
    # log_portfolio_operation("fetch_dividend_history", "started", execution_time=0, details={"ticker": ticker, "start_date": start_date, "end_date": end_date})
    
    def _api_pull() -> pd.DataFrame:
        params = {"symbol": ticker, "apikey": API_KEY}
        if start_date:
            params["from"] = pd.to_datetime(start_date).date().isoformat()
        if end_date:
            params["to"] = pd.to_datetime(end_date).date().isoformat()
    
        # Same error handling pattern as existing functions
        import time
        from utils.logging import log_rate_limit_hit, log_service_health, log_critical_alert
        start_time = time.time()
        
        resp = requests.get(f"{BASE_URL}/dividends", params=params, timeout=DIVIDEND_API_TIMEOUT)
        
        # Rate limiting detection
        if resp.status_code == 429:
            log_rate_limit_hit(None, "dividends", "api_calls", None, "free")
            log_service_health("FMP_API", "degraded", time.time() - start_time, {"error": "rate_limited", "status_code": 429})
        
        try:
            resp.raise_for_status()
            response_time = time.time() - start_time
            log_service_health("FMP_API", "healthy", response_time, user_id=None)
        except requests.exceptions.HTTPError as e:
            response_time = time.time() - start_time
            log_critical_alert("api_connection_failure", "high", f"FMP Dividends API failed for {ticker}", "Retry with exponential backoff", details={"symbol": ticker, "endpoint": "dividends", "status_code": resp.status_code})
            log_service_health("FMP_API", "down", response_time, {"error": str(e), "status_code": resp.status_code})
            raise
        
        data = resp.json()
        if not data:  # Handle empty dividend history (growth stocks)
            return pd.DataFrame(columns=["adjDividend", "yield", "frequency"])
            
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        
        # LOGGING: Add data processing completion logging
        # log_portfolio_operation("fetch_dividend_history", "data_processed", execution_time=0, details={"ticker": ticker, "data_points": len(df), "date_range": f"{df.index[0] if not df.empty else 'N/A'} to {df.index[-1] if not df.empty else 'N/A'}"})
        
        # Return relevant columns for dividend analysis
        return df[["adjDividend", "yield", "frequency"]]
    
    return cache_read(
        key=[ticker, "dividends", start_date or "none", end_date or "none"],
        loader=_api_pull,
        cache_dir="cache_dividends",
        prefix=f"{ticker}_div",
    )


### `fetch_current_dividend_yield()` - Full Implementation  
@lru_cache(maxsize=DIVIDEND_LRU_SIZE)
def fetch_current_dividend_yield(ticker: str) -> float:
    """
    Get current annualized dividend yield for a ticker using CURRENT YIELD method.
    
    Method: Sum last 12 months of dividends / current price
    
    Args:
        ticker (str): Stock or ETF symbol.
        
    Returns:
        float: Annualized dividend yield as percentage (e.g., 2.34 for 2.34%)
    """
    # LOGGING: Add LRU cache layer logging for dividend yields
    # cache_info = fetch_current_dividend_yield.cache_info()
    # log_performance_metric("lru_cache_fetch_current_dividend_yield", cache_info.hits, cache_info.misses, details={"ticker": ticker, "cache_size": cache_info.currsize, "max_size": cache_info.maxsize})
    
    try:
        # Get dividend history (configurable lookback period)
        end_date = datetime.now()
        lookback_months = DIVIDEND_DEFAULTS.get("lookback_months", 12)  # Centralized default (V1: 12 months)
        start_date = end_date - pd.DateOffset(months=lookback_months)
        
        div_df = fetch_dividend_history(ticker, start_date, end_date)
        
        if div_df.empty:
            return 0.0  # No dividends (growth stock)
        
        # Sum dividends from last 12 months
        annual_dividends = div_df['adjDividend'].sum()
        
        # Get current price - avoid circular import by using data_loader directly
        try:
            prices = fetch_monthly_close(ticker)  # Get recent price data
            if prices.empty:
                return 0.0  # No price data available
            current_price = prices.dropna().iloc[-1]  # Most recent non-null price
        except Exception:
            return 0.0  # Price fetch failed
        
        # Handle edge cases with pricing data
        if current_price <= 0 or current_price is None:
            return 0.0  # No valid current price available
        
        # Handle edge case: very small dividend amounts
        if annual_dividends <= 0:
            return 0.0  # No meaningful dividends
            
        # Calculate annualized yield percentage
        dividend_yield = (annual_dividends / current_price) * 100
        
        # Handle edge case: unrealistic yield (possible data error)
        # Handle edge case: unrealistic yield (possible data error)
        # Note: REITs can legitimately yield 8-12%, some dividend stocks 6-8%
        if dividend_yield > DIVIDEND_DATA_QUALITY_THRESHOLD * 100:  # Use configurable threshold (default 25%)
            from utils.logging import log_portfolio_operation
            log_portfolio_operation("dividend_yield_data_quality_warning", "warning", execution_time=0, 
                                   details={"ticker": ticker, "calculated_yield": dividend_yield, "reason": "unusually_high_yield", "threshold": DIVIDEND_DATA_QUALITY_THRESHOLD * 100})
            return 0.0
        
        return round(dividend_yield, 4)
        
    except Exception as e:
        # Graceful fallback for any errors
        from utils.logging import log_portfolio_operation
        log_portfolio_operation("dividend_yield_calculation_failed", "error", execution_time=0, 
                               details={"ticker": ticker, "error": str(e), "error_type": type(e).__name__})
        return 0.0
```

**Import Requirements**:
```python
# In data_loader.py - ADD to existing imports (around line 23)
from utils.config import (
    DATA_LOADER_LRU_SIZE, TREASURY_RATE_LRU_SIZE, DIVIDEND_LRU_SIZE,
    DIVIDEND_DATA_QUALITY_THRESHOLD, DIVIDEND_API_TIMEOUT
)
from settings import DIVIDEND_DEFAULTS  # ← ADD THIS IMPORT
from datetime import datetime, UTC
```

**LRU Cache Integration** (Add at end of data_loader.py, around line 419):
```python
# Add after existing LRU cache wrappers
_fetch_dividend_history_disk = fetch_dividend_history

# Re-wrap fetch_current_dividend_yield with LRU cache (already has @lru_cache decorator above)
# NOTE: fetch_current_dividend_yield already has @lru_cache(maxsize=DIVIDEND_LRU_SIZE)
# so no additional LRU wrapper needed - just ensure import is correct
```

**Integration Points**:
- Follow same patterns as `fetch_monthly_total_return_price()`
- Use existing `cache_read()` infrastructure with `cache_dividends` prefix
- Same error handling and logging patterns
- LRU cache layer for frequently accessed data (using centralized `DIVIDEND_LRU_SIZE`)
- **IMPORTANT**: Avoid circular imports by using `fetch_monthly_close()` instead of `latest_price()` from `run_portfolio_risk.py`

### 2. Portfolio Engine (`portfolio_risk.py`)

**Required Import** (Add after line 23):
```python
# ADD this import for dividend calculation
from data_loader import fetch_current_dividend_yield
```

**Function Placement**: Add the following functions around **line 1100-1200** (near other portfolio calculation functions like `calculate_portfolio_performance_metrics`)

**New Functions**:

### `calculate_portfolio_dividend_yield()` - Full Implementation
```python  
def calculate_portfolio_dividend_yield(
    weights: Dict[str, float],
    portfolio_value: Optional[float] = None
) -> Dict[str, Any]:
    """
    Calculate weighted portfolio dividend yield using CURRENT YIELD method.
    
    Method: Weight individual current yields by portfolio allocation
    
    Args:
        weights (Dict[str, float]): Portfolio weights by ticker
        portfolio_value (float, optional): Total portfolio value for dollar estimates
    
    Returns:
        Dict[str, Any]: Dividend analysis results
    """
    
    # Get individual dividend yields for all tickers
    individual_yields = {}
    failed_tickers = []
    
    for ticker in weights:
        try:
            yield_pct = fetch_current_dividend_yield(ticker)
            individual_yields[ticker] = yield_pct
        except Exception as e:
            individual_yields[ticker] = 0.0
            failed_tickers.append(ticker)
    
    # Calculate weighted portfolio yield  
    portfolio_yield = sum(
        individual_yields[ticker] * weight 
        for ticker, weight in weights.items()
    )
    
    # Calculate dividend coverage metrics
    positions_with_dividends = sum(1 for yield_val in individual_yields.values() if yield_val > 0)
    coverage_by_count = positions_with_dividends / len(weights) if weights else 0
    
    # Weight-based coverage (positions with dividends)
    weight_with_dividends = sum(
        weight for ticker, weight in weights.items() 
        if individual_yields.get(ticker, 0) > 0
    )
    coverage_by_weight = weight_with_dividends / sum(weights.values()) if weights else 0
    
    # Calculate individual contribution to portfolio dividend income
    dividend_contributions = {}
    for ticker, weight in weights.items():
        ticker_yield = individual_yields[ticker]
        contribution_pct = (ticker_yield * weight / portfolio_yield * 100) if portfolio_yield > 0 else 0
        dividend_contributions[ticker] = {
            "yield": ticker_yield,
            "weight": weight * 100,  # Convert to percentage
            "contribution_pct": round(contribution_pct, 1)
        }
    
    # Build result dictionary
    result = {
        "portfolio_dividend_yield": round(portfolio_yield, 4),
        "individual_yields": {k: round(v, 4) for k, v in individual_yields.items()},
        "dividend_contributions": dividend_contributions,
        "data_quality": {
            "coverage_by_count": round(coverage_by_count, 3),
            "coverage_by_weight": round(coverage_by_weight, 3),
            "positions_with_dividends": positions_with_dividends,
            "total_positions": len(weights),
            "failed_tickers": failed_tickers
        }
    }
    
    # Add dollar estimate if portfolio value available
    if portfolio_value and portfolio_value > 0:
        estimated_annual_dividends = portfolio_value * (portfolio_yield / 100)
        result["estimated_annual_dividends"] = round(estimated_annual_dividends, 2)
        
        # Add top dividend contributors in dollar terms
        top_contributors = []
        for ticker, contrib in dividend_contributions.items():
            if contrib["yield"] > 0:
                dollar_contribution = estimated_annual_dividends * (contrib["contribution_pct"] / 100)
                top_contributors.append({
                    "ticker": ticker,
                    "yield": contrib["yield"],
                    "annual_dividends": round(dollar_contribution, 2),
                    "contribution_pct": contrib["contribution_pct"]
                })
        
        # Sort by dollar contribution and take top 5
        top_contributors.sort(key=lambda x: x["annual_dividends"], reverse=True)
        result["top_dividend_contributors"] = top_contributors[:5]
    
    return result


### Helper function
def get_dividend_dataframe(
    weights: Dict[str, float],
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Fetch dividend data for all portfolio tickers (similar pattern to get_returns_dataframe).
    
    Args:
        weights (Dict[str, float]): Portfolio weights by ticker
        start_date (str): Start date in 'YYYY-MM-DD' format
        end_date (str): End date in 'YYYY-MM-DD' format
        
    Returns:
        pd.DataFrame: Dividend history for all tickers, aligned and cleaned
    """
    dividend_data = {}
    for ticker in weights:
        try:
            div_df = fetch_dividend_history(ticker, start_date=start_date, end_date=end_date)
            dividend_data[ticker] = div_df['adjDividend'] if not div_df.empty else pd.Series(dtype=float)
        except Exception:
            dividend_data[ticker] = pd.Series(dtype=float)  # Empty series for failed tickers
    
    return pd.DataFrame(dividend_data).fillna(0)
```

### 3. Performance Integration

**Enhanced Performance Metrics**:

Update `calculate_portfolio_performance_metrics()` to include:

```python
# Add to performance metrics dictionary
performance_metrics.update({
    "dividend_metrics": {
        "portfolio_dividend_yield": float,        # % annual yield
        "total_annual_dividends": float,          # $ amount estimate  
        "dividend_coverage": float,               # % of portfolio with dividend data
        "top_dividend_contributors": List[Dict], # Top 5 dividend-paying positions
        "yield_by_sector": Dict[str, float]      # If sector data available
    }
})
```

### 4. Caching Strategy (Monthly-Stable, No TTL)

**Cache Structure**:
- **Namespace**: `cache_dividends/`
- **Key Pattern**: `{ticker}_div_{startYYYYMM}_{endYYYYMM}_{version}.parquet`
  - Normalize dates to month tokens (YYYYMM). Example: `AAPL_div_202409_202508_v1.parquet`
- **TTL**: None (no time-based expiry)
- **LRU Layer**: In-memory cache for current yield lookups via `@lru_cache(maxsize=DIVIDEND_LRU_SIZE)`

**Cache Invalidation / Refresh Behavior**:
- Natural monthly refresh: a new file is created when `endYYYYMM` changes (e.g., at month roll)
- Historical data is reused until the date range changes
- Use a version token for schema changes when needed

**Implementation Notes**:
- Compute `end_month` as the last complete month; compute `start_month = end_month - (lookback_months - 1)`
- Price for yield calculation should align to the same `end_month` (use last monthly close)

## Data Flow Architecture

### Current Performance Analysis Flow
```
1. core/performance_analysis.py: analyze_performance()
   ├─ Load portfolio config
   ├─ standardize_portfolio_input() → gets weights + total_value
   ├─ calculate_portfolio_performance_metrics(weights, dates)
   └─ Return PerformanceResult
```

### Enhanced Flow with Dividend Integration
```
1. core/performance_analysis.py: analyze_performance()
   ├─ Load portfolio config
   ├─ standardize_portfolio_input() → gets weights + total_value ✅
   ├─ calculate_portfolio_performance_metrics(weights, dates, total_value) ← NEW
   │  ├─ [existing performance calculations]
   │  ├─ calculate_portfolio_dividend_yield(weights, total_value) ← NEW
   │  └─ return enhanced performance_metrics with dividend_metrics
   └─ Return PerformanceResult with dividend data
```

### Detailed Data Flow
```
Portfolio Input → standardize_portfolio_input() → weights + total_value
                                               ↓
                Portfolio Weights → get_dividend_dataframe() → fetch_dividend_history()
                     +                                      ↓
                Total Value          Individual Ticker Dividend Data
                     ↓                            ↓
                calculate_portfolio_dividend_yield(weights, total_value)
                                           ↓
                    Weighted Portfolio Dividend Metrics + Dollar Estimates
                                           ↓
              calculate_portfolio_performance_metrics() [ENHANCED]
                                           ↓
                    Performance Results + Dividend Metrics
```

## Calculation Methodology

### Current Yield Method (Selected)
```python
# For each ticker:
# 1. Get last 12 months of dividend payments from FMP
# 2. Sum total dividends paid (using adjDividend field)
# 3. Divide by current price for annualized yield percentage
# 4. Weight by portfolio allocation

portfolio_yield = sum(ticker_yield * weight for ticker, weight in weights.items())

# Example:
# AAPL: $1.04 annual dividends / $230 price = 0.45% yield, 20% weight → 0.09%
# MSFT: $3.00 annual dividends / $420 price = 0.71% yield, 30% weight → 0.21%  
# Total portfolio yield = 0.09% + 0.21% + ... = Portfolio Dividend Yield
```

**Why Current Yield**:
- ✅ **Simple & Intuitive**: Easy to understand and explain
- ✅ **Forward-Looking**: Represents expected annual income
- ✅ **Industry Standard**: Most common dividend yield calculation
- ✅ **Fast Performance**: No complex time-weighting calculations

### Mathematical Equivalence: Portfolio Value vs. Individual Shares

**Method 1: Using Individual Shares**
```python
# For each position:
annual_dividend_per_share = sum_of_last_12_months_dividends_per_share
total_annual_dividends_for_position = shares * annual_dividend_per_share
total_portfolio_dividends = sum(position_dividends for all positions)
```

**Method 2: Using Portfolio Value + Yield (Selected)**
```python
# Calculate weighted portfolio yield:
portfolio_yield = sum(individual_yield * weight for each position)
# Apply to total portfolio value:
total_portfolio_dividends = portfolio_value * portfolio_yield
```

**Why Portfolio Value Method**:
- ✅ **Works with weight-based portfolios** (no shares needed)
- ✅ **Cleaner calculation** (one multiplication vs. summing individual positions)
- ✅ **Matches your architecture** (weight-based system)
- ✅ **Mathematically identical** to individual share calculations

## Integration Points & Code Changes

### Integration Architecture

**Key Integration Points**:
1. ✅ **Data Available**: `standardize_portfolio_input()` already provides both `weights` and `total_value`
2. ✅ **Natural Extension**: Add dividend calculation inside `calculate_portfolio_performance_metrics()`
3. ✅ **Conditional Dollars**: Show dollar amounts only when `total_value` is available
4. ✅ **Clean API**: Just add `total_value` parameter and `dividend_metrics` to results

### Required Code Changes

#### Change 1: `core/performance_analysis.py` - Exact Modifications

**Replace Line 72**:
```python
# CHANGE FROM:
weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]

# CHANGE TO:
standardized_data = standardize_portfolio_input(config["portfolio_input"], latest_price)
weights = standardized_data["weights"] 
total_value = standardized_data["total_value"]
```

**Modify Function Call** (Lines 75-80):
```python
# CHANGE FROM:
performance_metrics = calculate_portfolio_performance_metrics(
    weights=weights,
    start_date=config["start_date"],
    end_date=config["end_date"],
    benchmark_ticker=benchmark_ticker
)

# CHANGE TO:
performance_metrics = calculate_portfolio_performance_metrics(
    weights=weights,
    start_date=config["start_date"],
    end_date=config["end_date"],
    benchmark_ticker=benchmark_ticker,
    total_value=total_value  # ← ADD THIS LINE
)
```

**No Other Changes Required** - All other code in the function remains exactly the same.

#### Change 2: `portfolio_risk.py` - Exact Modifications

**Function Signature Change** (Line 982):
```python  
# CHANGE FROM:
def calculate_portfolio_performance_metrics(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = None
) -> Dict[str, Any]:

# CHANGE TO:
def calculate_portfolio_performance_metrics(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = None,
    total_value: Optional[float] = None  # ← ADD THIS PARAMETER
) -> Dict[str, Any]:
```

**Add Import** (After line 23):
```python
# ADD this import if not already present
from typing import Dict, Any, Optional  # ← Add Optional if not already imported
from data_loader import fetch_current_dividend_yield  # ← ADD this import
```

**Add Dividend Calculation** (After line 1213, before `return performance_metrics`):
```python
    # ADD: Dividend yield analysis
    try:
        dividend_metrics = calculate_portfolio_dividend_yield(
            weights=weights, 
            portfolio_value=total_value
        )
        performance_metrics["dividend_metrics"] = dividend_metrics
    except Exception as e:
        # Graceful fallback - don't break performance analysis
        performance_metrics["dividend_metrics"] = {
            "error": f"Dividend calculation failed: {str(e)}",
            "portfolio_dividend_yield": 0.0,
            "data_quality": {"coverage_by_weight": 0.0, "coverage_by_count": 0.0}
        }
    
    return performance_metrics  # ← EXISTING RETURN STATEMENT
```

#### Change 3: Function Signature Enhancement
```python
# Enhanced dividend calculation with portfolio value integration
def calculate_portfolio_dividend_yield(
    weights: Dict[str, float],
    portfolio_value: Optional[float] = None  # ← Integration with total_value
) -> Dict[str, Any]:
    """Calculate portfolio dividend yield with optional dollar estimates."""
    
    # Calculate percentage yield (always available)
    individual_yields = {}
    for ticker in weights:
        individual_yields[ticker] = fetch_current_dividend_yield(ticker)
    
    portfolio_yield = sum(
        individual_yields[ticker] * weight 
        for ticker, weight in weights.items()
    )
    
    dividend_metrics = {
        "portfolio_dividend_yield": portfolio_yield,
        "individual_yields": individual_yields,
        "dividend_coverage": calculate_dividend_coverage(weights, individual_yields),
    }
    
    # Add dollar estimate only if portfolio value available ← KEY INTEGRATION
    if portfolio_value:
        estimated_annual_dividends = portfolio_value * (portfolio_yield / 100)
        dividend_metrics["estimated_annual_dividends"] = estimated_annual_dividends
    
    return dividend_metrics
```

### Integration Benefits

**Seamless Integration**:
- ✅ **Minimal Changes**: Only 2 files need modification
- ✅ **Backward Compatible**: Existing performance analysis unchanged
- ✅ **Auto-Enhancement**: All performance calls get dividend data
- ✅ **Conditional Features**: Dollar amounts only when data available
- ✅ **Error Resilient**: Dividend failures don't break performance analysis

## Result Object Integration

### Enhanced `PerformanceResult` Class

**Correction**: `PerformanceResult` IS a @dataclass (line 2137-2138). 

**Add New Dataclass Field** (Around line 2140, after existing fields):
```python
@dataclass
class PerformanceResult:
    # ... existing fields ...
    dividend_metrics: Optional[Dict[str, Any]] = None  # ← ADD THIS FIELD
```

### CLI Output Integration - Exact Modifications

**Modify `display_portfolio_performance_metrics()`** in `run_portfolio_risk.py`:

**Add After Line 795** (after risk-free rate section):
```python
    # DIVIDEND ANALYSIS SECTION (NEW)
    if "dividend_metrics" in performance_metrics and performance_metrics["dividend_metrics"]:
        dividend_data = performance_metrics["dividend_metrics"]
        
        # Only show if no errors in dividend calculation
        if "error" not in dividend_data:
            print(f"\n💰 DIVIDEND ANALYSIS")
            print("─" * 40)
            
            # Portfolio dividend yield
            portfolio_yield = dividend_data.get("portfolio_dividend_yield", 0)
            print(f"📊 Portfolio Dividend Yield: {portfolio_yield:>6.2f}%")
            
            # Annual dividend estimate (if portfolio value available)
            if "estimated_annual_dividends" in dividend_data:
                annual_dividends = dividend_data["estimated_annual_dividends"]
                print(f"💵 Est. Annual Dividends:   ${annual_dividends:>8,.0f}")
            
            # Dividend coverage
            coverage = dividend_data.get("data_quality", {})
            coverage_pct = coverage.get("coverage_by_weight", 0) * 100
            positions_with_div = coverage.get("positions_with_dividends", 0)
            total_positions = coverage.get("total_positions", 0)
            print(f"📈 Dividend Coverage:      {coverage_pct:>6.1f}% ({positions_with_div}/{total_positions} positions)")
            
            # Top dividend contributors (if available)
            if "top_dividend_contributors" in dividend_data:
                top_contributors = dividend_data["top_dividend_contributors"][:3]  # Show top 3
                if top_contributors:
                    print(f"🏆 Top Dividend Contributors:")
                    for i, contrib in enumerate(top_contributors, 1):
                        ticker = contrib["ticker"]
                        yield_pct = contrib["yield"]
                        contribution = contrib["contribution_pct"]
                        print(f"   {i}. {ticker}: {yield_pct:.2f}% yield ({contribution:.1f}% of income)")
```

### API Response Integration - Exact Modifications

**Modify `to_api_response()`** in `core/result_objects.py` (After line 2611):
```python
            # Data quality information
            "excluded_tickers": self.excluded_tickers,
            "warnings": self.warnings,
            "analysis_notes": self.analysis_notes,
            # ADD DIVIDEND METRICS (NEW)
            "dividend_metrics": self.dividend_metrics  # ← ADD THIS LINE
        }
```

**Update Constructor Pattern** - Modify `from_core_analysis()` method (Around line 2424):
```python
@classmethod
def from_core_analysis(
    cls,
    performance_metrics: Dict[str, Any],
    analysis_period: Dict[str, Any],
    portfolio_summary: Dict[str, Any],
    analysis_metadata: Dict[str, Any],
    allocations: Optional[Dict[str, float]] = None
) -> "PerformanceResult":
    
    # ... existing field mappings ...
    
    return cls(
        # ... existing parameters ...
        dividend_metrics=performance_metrics.get("dividend_metrics"),  # ← ADD THIS LINE
        analysis_date=datetime.now(UTC),
        analysis_metadata=analysis_metadata,
        # ... rest unchanged ...
    )
```

**Complete PerformanceResult Integration Summary:**

1. ✅ **Dataclass Field**: `dividend_metrics: Optional[Dict[str, Any]] = None`
2. ✅ **Constructor Mapping**: `dividend_metrics=performance_metrics.get("dividend_metrics")`  
3. ✅ **API Response**: `"dividend_metrics": self.dividend_metrics`

### Complete API Response Structure with Dividend Metrics

**Enhanced API Response** will include:
```json
{
  "analysis_period": { "start_date": "2020-01-01", "end_date": "2025-06-01", "years": 5.4 },
  "returns": { "total_return": 89.2, "annualized_return": 13.4, "win_rate": 67.2 },
  "risk_metrics": { "volatility": 18.5, "maximum_drawdown": -12.3, "tracking_error": 4.1 },
  "risk_adjusted_returns": { "sharpe_ratio": 1.23, "sortino_ratio": 1.67, "calmar_ratio": 1.09 },
  "benchmark_analysis": { "benchmark_ticker": "SPY", "alpha_annual": 2.1, "beta": 1.02 },
  "dividend_metrics": {
    "portfolio_dividend_yield": 2.34,
    "estimated_annual_dividends": 5850.00,
    "individual_yields": {
      "AAPL": 0.45,
      "MSFT": 0.68,
      "JNJ": 2.85,
      "PG": 2.41,
      "TSLA": 0.00
    },
    "data_quality": {
      "coverage_by_count": 0.800,
      "coverage_by_weight": 0.850,
      "positions_with_dividends": 4,
      "total_positions": 5,
      "failed_tickers": []
    },
    "top_dividend_contributors": [
      { "ticker": "JNJ", "yield": 2.85, "annual_dividends": 1637.25, "contribution_pct": 28.0 },
      { "ticker": "MSFT", "yield": 0.68, "annual_dividends": 1287.00, "contribution_pct": 22.0 },
      { "ticker": "AAPL", "yield": 0.45, "annual_dividends": 877.50, "contribution_pct": 15.0 }
    ]
  },
  "analysis_date": "2025-06-27T10:30:00.000Z",
  "formatted_report": "[Complete CLI report with dividend section included]"
}
```

**Frontend Integration Points**:
- **Dividend Dashboard Card**: Use `dividend_metrics.portfolio_dividend_yield` and `estimated_annual_dividends`  
- **Portfolio Overview**: Display dividend coverage and top contributors
- **Holdings Table**: Show individual ticker yields from `dividend_metrics.individual_yields`
- **Income Analysis**: Chart dividend contribution percentages over time

## Error Handling & Data Quality - COMPREHENSIVE GRACEFUL DEGRADATION

### **Multi-Layer Error Handling Architecture**

Our dividend implementation includes **5 layers of graceful degradation** to ensure performance analysis never breaks:

#### **Layer 1: API Level (`fetch_dividend_history`)**
```python
# Handle empty dividend response (growth stocks)
if not data:  
    return pd.DataFrame(columns=["adjDividend", "yield", "frequency"])
```
✅ **Graceful Response**: Empty DataFrame for stocks with no dividend history

#### **Layer 2: Individual Yield Calculation (`fetch_current_dividend_yield`)**
```python  
if div_df.empty:
    return 0.0  # Growth stock - no dividends

if current_price <= 0 or current_price is None:
    return 0.0  # Invalid pricing data

if annual_dividends <= 0:
    return 0.0  # No meaningful dividends

if dividend_yield > 50.0:  # Data quality check
    log_portfolio_operation("dividend_yield_data_quality_warning", "warning", ...)
    return 0.0  # Unrealistic yield - likely data error

except Exception as e:
    log_portfolio_operation("dividend_yield_calculation_failed", "error", ...)
    return 0.0  # Complete fallback
```
✅ **Graceful Response**: Always returns 0.0% yield for any failure

#### **Layer 3: Portfolio Aggregation (`calculate_portfolio_dividend_yield`)**
```python
for ticker in weights:
    try:
        yield_pct = fetch_current_dividend_yield(ticker)
        individual_yields[ticker] = yield_pct
    except Exception as e:
        individual_yields[ticker] = 0.0  # Individual ticker failure
        failed_tickers.append(ticker)    # Track failures for reporting
```
✅ **Graceful Response**: Individual failures don't break portfolio calculation

#### **Layer 4: Performance Integration (`calculate_portfolio_performance_metrics`)**
```python
try:
    dividend_metrics = calculate_portfolio_dividend_yield(weights, total_value)
    performance_metrics["dividend_metrics"] = dividend_metrics
except Exception as e:
    # Complete dividend system failure - don't break performance analysis
    performance_metrics["dividend_metrics"] = {
        "error": f"Dividend calculation failed: {str(e)}",
        "portfolio_dividend_yield": 0.0,
        "data_quality": {"coverage_by_weight": 0.0, "coverage_by_count": 0.0}
    }
```
✅ **Graceful Response**: Returns error structure with 0% yield, preserves performance analysis

#### **Layer 5: Display Level (CLI/API)**
```python
# CLI Output
if "dividend_metrics" in performance_metrics and performance_metrics["dividend_metrics"]:
    dividend_data = performance_metrics["dividend_metrics"]
    if "error" not in dividend_data:
        # Show dividend section only if data available
        
# API Output  
"dividend_metrics": self.dividend_metrics  # Can be None or error structure
```
✅ **Graceful Response**: Silently omits dividend section if no valid data

### **Specific Edge Case Handling**

| **Scenario** | **Detection** | **Graceful Response** |
|--------------|---------------|---------------------|
| **Growth Stocks** | `div_df.empty` | Return 0.0% yield |
| **New IPOs** | Empty dividend history | Return 0.0% yield |
| **Delisted Stocks** | API errors, stale data | Return 0.0% yield, `log_portfolio_operation()` |
| **Pricing Issues** | `current_price <= 0` | Return 0.0% yield |
| **Data Corruption** | `dividend_yield > 50%` | Return 0.0% yield, `log_portfolio_operation()` |
| **API Rate Limits** | HTTP 429 responses | Use cached data, `log_service_health()` |
| **Network Failures** | Connection errors | Return 0.0% yield, `log_critical_alert()` |
| **Calculation Errors** | Math/division errors | Return 0.0% yield, `log_portfolio_operation()` |

### **Data Quality Metrics & Transparency**

**Coverage Reporting**:
```python
"data_quality": {
    "coverage_by_count": 0.800,      # 80% of positions have dividend data
    "coverage_by_weight": 0.850,     # 85% by portfolio weight  
    "positions_with_dividends": 4,   # Absolute count
    "total_positions": 5,            # Portfolio size
    "failed_tickers": ["TSLA"]       # Explicit failure tracking
}
```

**User Communication**:
- ✅ **Portfolio-level**: Coverage percentages show data completeness
- ✅ **Individual-level**: Failed tickers explicitly reported  
- ✅ **Quality indicators**: Warnings for unusual yields or data issues
- ✅ **Graceful omission**: Missing dividend section when no valid data

### **System Resilience Guarantees**

**✅ NEVER BREAKS PERFORMANCE ANALYSIS**: Dividend calculation failures are isolated and don't impact core portfolio performance metrics

**✅ MEANINGFUL DEFAULTS**: 0.0% yield is the correct default for growth stocks and failed calculations

**✅ TRANSPARENT ERRORS**: Failed calculations are logged via `log_portfolio_operation()` infrastructure, not hidden

**✅ DATA QUALITY VISIBILITY**: Users can see exactly what percentage of their portfolio has dividend data

**✅ PROGRESSIVE DEGRADATION**: System works with partial data and reports coverage levels

## Settings Integration

**Critical: Add to `utils/config.py`** (Following Centralized Pattern):

```python
# === Global Cache Settings === (ADD TO EXISTING SECTION)
DATA_LOADER_LRU_SIZE = int(os.getenv("DATA_LOADER_LRU_SIZE", "256"))
TREASURY_RATE_LRU_SIZE = int(os.getenv("TREASURY_RATE_LRU_SIZE", "64"))
DIVIDEND_LRU_SIZE = int(os.getenv("DIVIDEND_LRU_SIZE", "100"))  # ← ADD THIS LINE

# === Dividend Configuration Settings === (ADD NEW SECTION)
# Data quality and validation thresholds
DIVIDEND_DATA_QUALITY_THRESHOLD = float(os.getenv("DIVIDEND_DATA_QUALITY_THRESHOLD", "0.25"))  # 25% max yield before flagging as suspicious
DIVIDEND_MIN_COVERAGE_THRESHOLD = float(os.getenv("DIVIDEND_MIN_COVERAGE_THRESHOLD", "0.50"))  # 50% minimum portfolio coverage for reliable analysis

# Cache and performance settings  
DIVIDEND_CACHE_CLEANUP_INTERVAL = int(os.getenv("DIVIDEND_CACHE_CLEANUP_INTERVAL", "7"))  # days before cache cleanup
DIVIDEND_API_TIMEOUT = int(os.getenv("DIVIDEND_API_TIMEOUT", "30"))  # seconds for FMP dividend API calls
DIVIDEND_BATCH_SIZE = int(os.getenv("DIVIDEND_BATCH_SIZE", "5"))  # max concurrent dividend API calls
```

**Verify these settings exist before implementing the dividend functions!**

**New Settings in `settings.py`**:

```python
# Dividend calculation settings - CURRENT YIELD METHOD ONLY
DIVIDEND_DEFAULTS = {
    "lookback_months": 12,                    # For current yield calculation (12-month TTM)
    "min_dividend_data_coverage": 0.7,        # 70% of portfolio must have dividend data
    "include_zero_yield_positions": True,     # Include non-dividend paying stocks (0% yield)
}

# Cache settings (unused in V1 monthly-stable cache; kept for reference only)
# DIVIDEND_CACHE_TTL_HOURS = 24
```

## CLI Output Enhancement

**New Performance Report Section**:

```
📊 DIVIDEND ANALYSIS
├─ Portfolio Dividend Yield: 2.34% (annual)
├─ Total Annual Dividends: $2,847 (estimated)
├─ Dividend Coverage: 85% (17/20 positions)
└─ Top Dividend Contributors:
   • MSFT: 0.68% yield (28% of dividend income)
   • AAPL: 0.45% yield (22% of dividend income)  
   • JNJ:  2.85% yield (15% of dividend income)
```

## API Integration Points

**Enhanced Existing Endpoints**:
- `/api/performance` - Include dividend_metrics in response  
- `/api/direct/performance` - Include dividend_metrics in direct response

**New Endpoints** (if needed):
- `GET /api/dividend-yield` - Current portfolio dividend yield
- `GET /api/stock/{ticker}/dividends` - Individual ticker dividend history

## Implementation Phases - Current Yield Method

### Phase 1: Core Infrastructure (2-3 days)
1. ✅ **Data Layer**: Implement `fetch_dividend_history()` and `fetch_current_dividend_yield()`
   - Focus on 12-month trailing dividend data from FMP
   - Simple current price division for yield calculation
2. ✅ **Caching**: Extend cache system for dividend data
3. ✅ **Basic Calculation**: Current yield method only (no historical complexity)

### Phase 2: Portfolio Integration (1-2 days) 
1. ✅ **Portfolio Engine**: Implement `calculate_portfolio_dividend_yield()`
   - Weight-average individual current yields
   - Handle zero-dividend stocks (growth stocks)
2. ✅ **Performance Integration**: Add dividend metrics to performance calculation
3. ✅ **Error Handling**: Robust fallbacks for missing/partial data

### Phase 3: Output & Polish (1-2 days)
1. ✅ **CLI Output**: Enhanced performance report with dividend section
2. ✅ **Result Objects**: Update `PerformanceResult` with dividend data
3. ✅ **Settings Integration**: Add dividend configuration to settings

### Phase 4: Testing & Validation (1 day)
1. ✅ **Unit Tests**: Test dividend calculation functions
2. ✅ **Integration Tests**: Test with real portfolio data
3. ✅ **Edge Cases**: Zero-dividend stocks, data gaps, API failures

**Total Timeline**: 4-5 days (simplified from original plan due to current yield only)

## Risk Considerations

**Data Accuracy**:
- FMP dividend data quality and timeliness
- Adjustment for stock splits and special dividends
- Currency handling for international stocks

**Performance Impact**:
- Additional API calls per portfolio ticker
- Cache efficiency for dividend data
- Memory usage for dividend history storage

**Business Logic**:
- Treatment of REITs (higher yields, different tax implications)
- ETF dividend pass-through calculations
- Ex-dividend date timing effects

## Success Metrics

**Technical Success**:
- ✅ Dividend yield calculation accuracy within 0.1% of manual verification
- ✅ API response time increase < 500ms for typical portfolios
- ✅ Cache hit rate > 80% for dividend data
- ✅ Error rate < 2% for dividend data fetching

**Business Value**:
- ✅ Portfolio managers can assess income generation capacity
- ✅ Better alignment with income-focused investment strategies
- ✅ Enhanced portfolio analysis completeness

## Future Enhancements

**Phase 2 Features** (Future):
- Dividend growth rate calculation (3-year CAGR)
- Dividend sustainability metrics (payout ratios)
- Sector-based dividend analysis
- Dividend calendar (upcoming payment dates)
- Tax-adjusted dividend yields (if tax bracket known)

## Frontend Integration Points

### PerformanceAdapter Integration (`frontend/src/adapters/PerformanceAdapter.ts`)

**Backend API Response Structure** (Ready for Frontend):
```json
{
  "success": boolean,
  "performance_metrics": {
    // ... existing fields ...
    "dividend_metrics": {
      "portfolio_dividend_yield": 2.34,
      "estimated_annual_dividends": 5850.00,
      "individual_yields": { "AAPL": 0.45, "MSFT": 0.68, ... },
      "data_quality": { 
        "coverage_by_weight": 0.850, 
        "coverage_by_count": 0.800,
        "positions_with_dividends": 4,
        "total_positions": 5,
        "failed_tickers": []
      },
      "top_dividend_contributors": [
        { "ticker": "JNJ", "yield": 2.85, "annual_dividends": 1637.25, "contribution_pct": 28.0 },
        { "ticker": "MSFT", "yield": 0.68, "annual_dividends": 1287.00, "contribution_pct": 22.0 }
      ]
    }
  }
}
```

#### Required PerformanceAdapter Modifications

**1. Add to PerformanceResult interface** (around line 156):
```typescript
interface PerformanceResult {
  // ... existing fields ...
  dividend_metrics?: {
    portfolio_dividend_yield: number;
    estimated_annual_dividends?: number;
    individual_yields: Record<string, number>;
    data_quality: {
      coverage_by_weight: number;
      coverage_by_count: number;
      positions_with_dividends: number;
      total_positions: number;
      failed_tickers: string[];
    };
    top_dividend_contributors?: Array<{
      ticker: string;
      yield: number;
      annual_dividends: number;
      contribution_pct: number;
    }>;
  };
}
```

**2. Add to PerformanceData interface** (around line 214):
```typescript
interface PerformanceData {
  // ... existing fields ...
  dividend?: {
    portfolioYield: number;
    estimatedAnnualDividends?: number;
    individualYields: Record<string, number>;
    dataQuality: {
      coverageByWeight: number;
      coverageByCount: number;
      positionsWithDividends: number;
      totalPositions: number;
      failedTickers: string[];
    };
    topContributors?: Array<{
      ticker: string;
      yield: number;
      annualDividends?: number;
      contributionPct: number;
    }>;
  };
}
```

**3. Update performDataTransformation method** (around line 508, inside the return statement):
```typescript
private performDataTransformation(performance: PerformanceResult, fullApiResponse?: any): PerformanceData {
  // ... existing logic ...
  
  return {
    // ... existing fields ...
    
    // ADD: Direct dividend transformation (no separate method needed)
    dividend: performance.dividend_metrics ? {
      portfolioYield: performance.dividend_metrics.portfolio_dividend_yield,
      estimatedAnnualDividends: performance.dividend_metrics.estimated_annual_dividends,
      individualYields: performance.dividend_metrics.individual_yields,
      dataQuality: {
        coverageByWeight: performance.dividend_metrics.data_quality.coverage_by_weight,
        coverageByCount: performance.dividend_metrics.data_quality.coverage_by_count,
        positionsWithDividends: performance.dividend_metrics.data_quality.positions_with_dividends,
        totalPositions: performance.dividend_metrics.data_quality.total_positions,
        failedTickers: performance.dividend_metrics.data_quality.failed_tickers
      },
      topContributors: performance.dividend_metrics.top_dividend_contributors?.map(contrib => ({
        ticker: contrib.ticker,
        yield: contrib.yield,
        annualDividends: contrib.annual_dividends,
        contributionPct: contrib.contribution_pct
      }))
    } : undefined,  // ← ADD INSIDE EXISTING RETURN OBJECT
  };
}
```

#### Integration Benefits

**✅ SEAMLESS INTEGRATION**:
- **Zero Hook Changes**: `usePerformance.ts` requires no modifications
- **Automatic Caching**: Dividend data cached with same TTL as performance data (30min)
- **Type Safety**: Full TypeScript support through interface updates
- **Error Handling**: Graceful degradation if `dividend_metrics` missing from API
- **Consistent UX**: Follows existing performance metrics display patterns

**✅ DATA FLOW**:
```
Backend: performance_metrics.dividend_metrics 
  ↓
PerformanceAdapter: .transform() → data.dividend
  ↓  
usePerformance: hook returns transformed data (no changes needed)
  ↓
PerformanceViewContainer: passes data to component (no changes needed)
  ↓
PerformanceView: can access data.dividend for display (UI updates separate)
```

### Frontend Implementation Strategy

**Phase 1**: Backend + PerformanceAdapter (This Plan)
- ✅ Backend dividend calculation implementation
- ✅ PerformanceAdapter modifications for data transformation
- ✅ Data available in frontend via existing `usePerformance()` hook

**Phase 2**: UI Components (Separate Planning)
- 🔄 PerformanceView dividend section integration
- 🔄 New dividend-specific components (DividendAnalysisTab, etc.)
- 🔄 UI design review and UX optimization

## Architecture Compliance

This implementation follows established patterns:
- ✅ **Consistent with existing data loaders** (`fetch_monthly_*` functions)  
- ✅ **Uses established caching infrastructure** (`cache_read/write`)
- ✅ **Follows logging patterns** (error handling decorators)
- ✅ **Integrates with performance engine** (`calculate_portfolio_performance_metrics`)
- ✅ **Maintains result object architecture** (`PerformanceResult` enhancement)
- ✅ **Preserves CLI/API dual interface** pattern
- ✅ **Frontend adapter pattern** (seamless PerformanceAdapter integration)
- ✅ **Zero breaking changes** (backward compatible with existing UI)

---

**Implementation Priority**: 
1. **Phase 1**: Backend dividend implementation + PerformanceAdapter updates
2. **Phase 2**: UI component integration (separate planning/review cycle)

**Next Steps**: Proceed with Phase 1 implementation starting with data layer functions.
