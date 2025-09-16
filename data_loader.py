#!/usr/bin/env python
# coding: utf-8

# In[1]:


# File: data_loader.py
"""
Data loading and caching utilities for portfolio risk analysis.

This module provides data loaders with intelligent caching for:
- Month-end equity prices (close and dividend-adjusted total return)
- Monthly Treasury rates (for risk-free calculations)
- Dividend history and current dividend yield computation

Caching model:
- Disk cache: Parquet-backed with deterministic keys
- Monthly-stable dividends: Cache keys use month tokens (YYYYMM) so data naturally
  refreshes on calendar month roll without TTL
- In-memory LRU: Frequently called helpers are wrapped with lru_cache

Core data loaders:
- fetch_monthly_close: Month-end close prices (fallback path)
- fetch_monthly_total_return_price: Dividend-adjusted total return prices (preferred)
- fetch_monthly_treasury_rates: Treasury yield levels (percent)
- fetch_dividend_history: Dividend events between month-end bounds using FMP /dividends
- fetch_current_dividend_yield: Current yield via TTM adjDividend / month-end price

Notes:
- All return computations prefer total-return series when available; close-only series
  serve as a safe fallback when adjusted data is unavailable
- Current dividend yield uses trailing 12 months of adjDividend divided by the latest
  month-end price (aligned to the same month window); unusually large yields are
  guarded by a configurable data quality threshold and return 0.0 when exceeded
"""

from __future__ import annotations
from pathlib import Path
from typing import Iterable, Callable, Union, Optional
import hashlib
import pandas as pd
from pandas.errors import EmptyDataError, ParserError

# Add logging decorator imports
from utils.logging import (
    log_cache_operations,
    log_performance,
    log_api_health,
    log_portfolio_operation,
    log_error_handling,
    log_critical_alert
)
from utils.config import (
    DATA_LOADER_LRU_SIZE,
    TREASURY_RATE_LRU_SIZE,
    DIVIDEND_LRU_SIZE,
    DIVIDEND_DATA_QUALITY_THRESHOLD,
    DIVIDEND_API_TIMEOUT,
)
from settings import DIVIDEND_DEFAULTS

# ── internals ──────────────────────────────────────────────────────────
def _hash(parts: Iterable[str | int | float]) -> str:
    key = "_".join(str(p) for p in parts if p is not None)
    return hashlib.md5(key.encode()).hexdigest()[:8]

def _safe_load(path: Path) -> Optional[pd.DataFrame]:
    try:
        return pd.read_parquet(path)
    except (EmptyDataError, ParserError, OSError, ValueError) as e:
        # LOGGING: Add cache file corruption logging
        # log_critical_alert("cache_file_corrupted", "medium", f"Cache file corrupted: {path.name}", "Delete and regenerate", details={"path": str(path), "error": str(e)})
        print(f"⚠️  Cache file corrupted, deleting: {path.name} ({type(e).__name__}: {e})")
        path.unlink(missing_ok=True)          # drop corrupt file
        return None

# ── public API ────────────────────────────────────────────────────────
def cache_read(
    *,
    key: Iterable[str | int | float],
    loader: Callable[[], Union[pd.Series, pd.DataFrame]],
    cache_dir: Union[str, Path] = "cache",
    prefix: Optional[str] = None,
) -> Union[pd.Series, pd.DataFrame]:
    """
    Returns cached object if present, else computes via `loader()` and caches.

    Example
    -------
    series = cache_read(
        key     = ["SPY", "2020-01", "2024-06"],
        loader  = lambda: expensive_fetch(...),
        cache_dir = "cache_prices",
        prefix  = "SPY",
    )
    """
    # LOGGING: Add cache operation start logging
    # log_portfolio_operation("cache_read", "started", execution_time=0, details={"key": list(key), "cache_dir": str(cache_dir), "prefix": prefix})
    cache_dir = Path(cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{prefix or key[0]}_{_hash(key)}.parquet"
    path  = cache_dir / fname

    if path.is_file():
        df = _safe_load(path)
        if df is not None:
            # LOGGING: Add cache hit logging
            # log_portfolio_operation("cache_read", "cache_hit", execution_time=0, details={"key": list(key), "file": fname, "shape": df.shape})
            return df.iloc[:, 0] if df.shape[1] == 1 else df

    # LOGGING: Add cache miss logging and loader execution
    # log_portfolio_operation("cache_read", "cache_miss", execution_time=0, details={"key": list(key), "file": fname})
    obj = loader()                                    # cache miss → compute
    df  = obj.to_frame(name=obj.name or "value") if isinstance(obj, pd.Series) else obj
    df.to_parquet(path, engine="pyarrow", compression="zstd", index=True)
    # LOGGING: Add cache write completion logging
    # log_portfolio_operation("cache_read", "cache_written", execution_time=0, details={"key": list(key), "file": fname, "shape": df.shape})
    return obj


def cache_write(
    obj: Union[pd.Series, pd.DataFrame],
    *,
    key: Iterable[str | int | float],
    cache_dir: Union[str, Path] = "cache",
    prefix: Optional[str] = None,
) -> Path:
    """
    Force-write `obj` under a key.  Returns the Path written.
    """
    # LOGGING: Add cache write operation logging
    # log_portfolio_operation("cache_write", "started", execution_time=0, details={"key": list(key), "cache_dir": str(cache_dir), "prefix": prefix, "shape": obj.shape})
    cache_dir = Path(cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{prefix or key[0]}_{_hash(key)}.parquet"
    path  = cache_dir / fname
    df    = obj.to_frame(name=obj.name or "value") if isinstance(obj, pd.Series) else obj
    df.to_parquet(path, engine="pyarrow", compression="zstd", index=True)
    # LOGGING: Add cache write completion logging
    # log_portfolio_operation("cache_write", "completed", execution_time=0, details={"key": list(key), "file": fname, "path": str(path)})
    return path


# In[2]:


# File: data_loader.py

import requests
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import datetime
from typing import Optional, Union, List, Dict
from dotenv import load_dotenv
import os
import time
from dotenv import load_dotenv

# Load .env file before accessing environment variables
load_dotenv()

# Configuration
FMP_API_KEY = os.getenv("FMP_API_KEY")
API_KEY  = FMP_API_KEY
BASE_URL = "https://financialmodelingprep.com/stable"


@log_error_handling("high")
def fetch_monthly_close(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date:   Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Fetch month-end closing prices for a given ticker from FMP.

    Uses the `/stable/historical-price-eod/full` endpoint with optional
    `from` and `to` parameters, then resamples to month-end.

    Args:
        ticker (str):       Stock or ETF symbol.
        start_date (str|datetime, optional): Earliest date (inclusive).
        end_date   (str|datetime, optional): Latest date (inclusive).

    Returns:
        pd.Series: Month-end close prices indexed by date.
    """
    # LOGGING: Add FMP API data fetch request logging
    # log_portfolio_operation("fetch_monthly_close", "started", execution_time=0, details={"ticker": ticker, "start_date": start_date, "end_date": end_date})
    
    # ----- loader (runs only on cache miss) ------------------------------
    def _api_pull() -> pd.Series:
        params = {"symbol": ticker, "apikey": API_KEY, "serietype": "line"}
        if start_date:
            params["from"] = pd.to_datetime(start_date).date().isoformat()
        if end_date:
            params["to"]   = pd.to_datetime(end_date).date().isoformat()
    
        # LOGGING: Add FMP API call logging with timing and rate limiting
        import time
        from utils.logging import log_rate_limit_hit, log_service_health, log_critical_alert
        start_time = time.time()
        
        resp = requests.get(f"{BASE_URL}/historical-price-eod/full", params=params, timeout=30)
        
        # LOGGING: Add rate limit detection for FMP API
        if resp.status_code == 429:
            log_rate_limit_hit(None, "historical-price-eod", "api_calls", None, "free")
            log_service_health("FMP_API", "degraded", time.time() - start_time, {"error": "rate_limited", "status_code": 429})
        
        try:
            resp.raise_for_status()
            
            # LOGGING: Add service health monitoring for FMP API connection (success case)
            response_time = time.time() - start_time
            log_service_health("FMP_API", "healthy", response_time, user_id=None)
            
        except requests.exceptions.HTTPError as e:
            # LOGGING: Add critical alert for FMP API connection failure
            response_time = time.time() - start_time
            log_critical_alert("api_connection_failure", "high", f"FMP API connection failed for {ticker}", "Retry with exponential backoff", details={"symbol": ticker, "endpoint": "historical-price-eod", "status_code": resp.status_code})
            log_service_health("FMP_API", "down", response_time, {"error": str(e), "status_code": resp.status_code})
            raise
        
        raw  = resp.json()
        data = raw if isinstance(raw, list) else raw.get("historical", [])

        df = pd.DataFrame(data)
        if df.empty or "date" not in df.columns:
            log_critical_alert("empty_api_data", "high", f"EMPTY DATA ERROR: Ticker={ticker}, Endpoint=close_price, Columns={list(df.columns)}, Shape={df.shape}", "Check ticker validity and API access")
            raise ValueError(f"No data or date column found for ticker {ticker} in close price data. Columns: {list(df.columns)}")
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        monthly = df.sort_index().resample("ME")["close"].last()
        
        # LOGGING: Add data processing completion logging
        # log_portfolio_operation("fetch_monthly_close", "data_processed", execution_time=0, details={"ticker": ticker, "data_points": len(monthly), "date_range": f"{monthly.index[0]} to {monthly.index[-1]}"})
        
        return monthly

    # ----- call cache layer ---------------------------------------------
    return cache_read(
        key=[ticker, start_date or "none", end_date or "none"],
        loader=_api_pull,
        cache_dir="cache_prices",
        prefix=ticker,
    )


@log_error_handling("high")
def fetch_monthly_total_return_price(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Fetch dividend-adjusted month-end prices (total return) from FMP.

    Primary: /historical-price-eod/dividend-adjusted (adjClose)
    Fallback: /historical-price-eod/full (close) – flagged as price-only via name suffix.
    """
    def _api_pull() -> pd.Series:
        params = {"symbol": ticker, "apikey": API_KEY}
        if start_date:
            params["from"] = pd.to_datetime(start_date).date().isoformat()
        if end_date:
            params["to"] = pd.to_datetime(end_date).date().isoformat()

        try:
            resp = requests.get(f"{BASE_URL}/historical-price-eod/dividend-adjusted", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            df = pd.DataFrame(data)
            if df.empty or "date" not in df.columns:
                log_critical_alert("empty_api_data", "high", f"EMPTY DATA ERROR: Ticker={ticker}, Endpoint=dividend-adjusted, Columns={list(df.columns)}, Shape={df.shape}", "Check ticker validity and API access")
                raise ValueError(f"No data or date column found for ticker {ticker} in dividend-adjusted data. Columns: {list(df.columns)}")
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            ser = df.resample("ME")["adjClose"].last()
            ser.name = f"{ticker}_total_return"
            return ser
        except Exception as e:
            # Fallback to close-only path
            try:
                params_fb = dict(params)
                params_fb["serietype"] = "line"
                resp = requests.get(f"{BASE_URL}/historical-price-eod/full", params=params_fb, timeout=30)
                resp.raise_for_status()
                raw = resp.json()
                data = raw if isinstance(raw, list) else raw.get("historical", [])
                df = pd.DataFrame(data)
                if df.empty or "date" not in df.columns:
                    log_critical_alert("empty_api_data", "high", f"EMPTY DATA ERROR: Ticker={ticker}, Endpoint=fallback_full, Columns={list(df.columns)}, Shape={df.shape}", "Check ticker validity and API access")
                    raise ValueError(f"No data or date column found for ticker {ticker} in fallback data. Columns: {list(df.columns)}")
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                ser = df.resample("ME")["close"].last()
                ser.name = f"{ticker}_price_only"
                return ser
            except Exception as fallback_error:
                raise ValueError(f"Both primary and fallback data fetch failed for ticker {ticker}. Primary error: {str(e)}. Fallback error: {str(fallback_error)}")

    # Separate cache namespace/prefix to avoid collisions with close-only
    return cache_read(
        key=[ticker, "dividend_adjusted", start_date or "none", end_date or "none"],
        loader=_api_pull,
        cache_dir="cache_prices",
        prefix=f"{ticker}_tr_v1",
    )




@log_error_handling("high")
def fetch_monthly_treasury_rates(
    maturity: str = "month3",
    start_date: Optional[Union[str, datetime]] = None,
    end_date:   Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Fetch month-end Treasury rates for a given maturity from FMP.

    Uses the `/stable/treasury-rates` endpoint to get Treasury rates,
    then resamples to month-end to align with stock price data.

    Args:
        maturity (str): Treasury maturity ("month3", "month6", "year1", etc.)
        start_date (str|datetime, optional): Earliest date (inclusive).
        end_date   (str|datetime, optional): Latest date (inclusive).

    Returns:
        pd.Series: Month-end Treasury rates (as percentages) indexed by date.
    """
    # LOGGING: Add treasury rates fetch request logging
    # log_portfolio_operation("fetch_monthly_treasury_rates", "started", execution_time=0, details={"maturity": maturity, "start_date": start_date, "end_date": end_date})
    
    # ----- loader (runs only on cache miss) ------------------------------
    def _api_pull() -> pd.Series:
        params = {"apikey": API_KEY}
        if start_date:
            params["from"] = pd.to_datetime(start_date).date().isoformat()
        if end_date:
            params["to"] = pd.to_datetime(end_date).date().isoformat()
        
        # LOGGING: Add FMP API call logging for treasury rates
        import time
        from utils.logging import log_rate_limit_hit, log_service_health, log_critical_alert
        start_time = time.time()
        
        resp = requests.get(f"{BASE_URL}/treasury-rates", params=params, timeout=30)
        
        # LOGGING: Add rate limit detection for treasury rates endpoint
        if resp.status_code == 429:
            log_rate_limit_hit(None, "treasury-rates", "api_calls", None, "free")
            log_service_health("FMP_API", "degraded", time.time() - start_time, {"error": "rate_limited", "endpoint": "treasury-rates"})
        
        try:
            resp.raise_for_status()
            
            # LOGGING: Add service health monitoring for treasury rates API (success case)
            response_time = time.time() - start_time
            log_service_health("FMP_API", "healthy", response_time, user_id=None)
            
        except requests.exceptions.HTTPError as e:
            # LOGGING: Add critical alert for treasury rates API failure
            response_time = time.time() - start_time
            log_critical_alert("api_connection_failure", "high", f"FMP Treasury rates API failed for {maturity}", "Retry with exponential backoff", details={"maturity": maturity, "endpoint": "treasury-rates", "status_code": resp.status_code})
            log_service_health("FMP_API", "down", response_time, {"error": str(e), "status_code": resp.status_code})
            raise
        
        raw = resp.json()
        
        # Create DataFrame from API response
        df = pd.DataFrame(raw)
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        
        # Extract the specified maturity column
        if maturity not in df.columns:
            available = list(df.columns)
            # LOGGING: Add critical alert for invalid maturity
            log_critical_alert("invalid_treasury_maturity", "medium", f"Treasury maturity '{maturity}' not available", "Use valid maturity from available options", details={"maturity": maturity, "available": available})
            raise ValueError(f"Maturity '{maturity}' not available. Available: {available}")
        
        # Sort by date (API already filtered by date range)
        df_sorted = df.sort_index()
        
        # Resample to month-end (align with stock prices)
        monthly = df_sorted.resample("ME")[maturity].last()
        monthly.name = f"treasury_{maturity}"
        
        # LOGGING: Add treasury rates processing completion logging
        # log_portfolio_operation("fetch_monthly_treasury_rates", "data_processed", execution_time=0, details={"maturity": maturity, "data_points": len(monthly), "date_range": f"{monthly.index[0]} to {monthly.index[-1]}"})
        
        return monthly

    # ----- call cache layer ---------------------------------------------
    return cache_read(
        key=["treasury", maturity, start_date or "none", end_date or "none"],
        loader=_api_pull,
        cache_dir="cache_prices",
        prefix=f"treasury_{maturity}",
    )


# ── Dividends (monthly-stable cache) ─────────────────────────────────────────

@log_error_handling("high")
def fetch_dividend_history(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
) -> pd.DataFrame:
    """
    Fetch dividend history for a ticker from FMP using frequency-based TTM calculation.

    This function retrieves all dividend history from FMP and applies intelligent filtering
    to select the most recent N observations based on dividend payment frequency,
    ensuring accurate trailing twelve month (TTM) dividend calculations.

    Algorithm:
    1. Fetch complete dividend history from FMP API (date parameters ignored by API)
    2. Sort by date (most recent first) 
    3. Determine payment frequency from data or frequency field
    4. Select appropriate number of observations:
       - Quarterly dividends: 4 most recent payments
       - Monthly dividends: 12 most recent payments  
       - Annual dividends: 1 most recent payment
    5. Return sorted by date (oldest first) for consistent processing

    Args:
        ticker (str): Stock ticker symbol (e.g., "STWD", "DSU")
        start_date (Optional[Union[str, datetime]]): Deprecated - kept for compatibility
        end_date (Optional[Union[str, datetime]]): Deprecated - kept for compatibility

    Returns:
        pd.DataFrame: DataFrame indexed by ex-dividend date with columns:
            - adjDividend (float): Adjusted dividend amount per share
            - yield (float): Dividend yield at payment date (informational)
            - frequency (str): Payment frequency ("Quarterly", "Monthly", etc.)

    Example:
        >>> df = fetch_dividend_history("STWD")
        >>> print(f"TTM dividends: ${df['adjDividend'].sum():.2f}")
        >>> print(f"Records: {len(df)} (quarterly = 4 expected)")
    """

    def _api_pull() -> pd.DataFrame:
        params = {"symbol": ticker, "apikey": API_KEY}
        # Remove date filtering - we want all dividend history to select most recent N observations

        # Basic API call with error handling similar to other loaders
        import time
        from utils.logging import log_rate_limit_hit, log_service_health, log_critical_alert
        t0 = time.time()
        resp = requests.get(f"{BASE_URL}/dividends", params=params, timeout=DIVIDEND_API_TIMEOUT)

        if resp.status_code == 429:
            log_rate_limit_hit(None, "dividends", "api_calls", None, "free")
            log_service_health("FMP_API", "degraded", time.time() - t0, {"error": "rate_limited", "status_code": 429})
        try:
            resp.raise_for_status()
            log_service_health("FMP_API", "healthy", time.time() - t0, user_id=None)
        except requests.exceptions.HTTPError as e:
            log_critical_alert("api_connection_failure", "high", f"FMP Dividends API failed for {ticker}", "Retry with backoff", details={"symbol": ticker, "endpoint": "dividends", "status_code": resp.status_code})
            log_service_health("FMP_API", "down", time.time() - t0, {"error": str(e), "status_code": resp.status_code})
            raise

        data = resp.json() or []
        if not data:
            return pd.DataFrame(columns=["adjDividend", "yield", "frequency"]).set_index(pd.Index([], name="date"))

        df = pd.DataFrame(data)
        if df.empty or "date" not in df.columns:
            return pd.DataFrame(columns=["adjDividend", "yield", "frequency"]).set_index(pd.Index([], name="date"))
        df["date"] = pd.to_datetime(df["date"])  # ex-dividend / payment date
        df = df.set_index("date").sort_index()

        # Keep known fields if present
        for col in ["adjDividend", "yield", "frequency"]:
            if col not in df.columns:
                df[col] = pd.NA
        
        # CRITICAL FIX: Use frequency-based TTM calculation instead of date filtering
        # Take the most recent N observations based on dividend frequency
        if not df.empty:
            # Sort by date (most recent first) to get latest dividends
            df_sorted = df.sort_index(ascending=False)
            
            # Determine how many observations we need for TTM based on frequency
            # Use the most recent dividend's frequency, or estimate from data
            if not df_sorted['frequency'].isna().all() and len(df_sorted) > 0:
                recent_frequency = df_sorted['frequency'].iloc[0]
                if pd.isna(recent_frequency):
                    # Estimate frequency from data spacing if not provided
                    if len(df_sorted) >= 2:
                        date_diff = (df_sorted.index[0] - df_sorted.index[1]).days
                        if date_diff < 40:  # ~Monthly
                            observations_needed = 12
                        elif date_diff < 120:  # ~Quarterly  
                            observations_needed = 4
                        else:  # ~Annual
                            observations_needed = 1
                    else:
                        observations_needed = 4  # Default to quarterly
                else:
                    frequency_lower = str(recent_frequency).lower()
                    if 'monthly' in frequency_lower or 'month' in frequency_lower:
                        observations_needed = 12
                    elif 'quarterly' in frequency_lower or 'quarter' in frequency_lower:
                        observations_needed = 4
                    elif 'annual' in frequency_lower or 'year' in frequency_lower:
                        observations_needed = 1
                    else:
                        observations_needed = 4  # Default to quarterly
            else:
                # Estimate from data spacing if no frequency info
                if len(df_sorted) >= 2:
                    date_diff = (df_sorted.index[0] - df_sorted.index[1]).days
                    if date_diff < 40:  # ~Monthly
                        observations_needed = 12
                    elif date_diff < 120:  # ~Quarterly
                        observations_needed = 4
                    else:  # ~Annual
                        observations_needed = 1
                else:
                    observations_needed = 4  # Default to quarterly
            
            # Take the most recent N observations for TTM calculation
            df = df_sorted.head(observations_needed).sort_index()
        
        return df[["adjDividend", "yield", "frequency"]]

    return cache_read(
        key=[ticker, "dividends", "frequency_based", "v2"],
        loader=_api_pull,
        cache_dir="cache_dividends", 
        prefix=f"{ticker}_div",
    )


from functools import lru_cache

@lru_cache(maxsize=DIVIDEND_LRU_SIZE)
def fetch_current_dividend_yield(ticker: str) -> float:
    """
    Calculate current annualized dividend yield using frequency-based TTM methodology.

    This function computes the current dividend yield by taking the most recent
    dividend payments (based on payment frequency) and annualizing them against
    the current stock price. Uses the same frequency-based logic as fetch_dividend_history.

    Methodology:
    1. Get TTM dividend payments using frequency-based selection
    2. Sum dividend payments for annualized dividend income  
    3. Fetch current stock price
    4. Calculate yield = (annual_dividends / current_price) * 100

    Frequency Logic:
    - Quarterly payers: Sum of last 4 dividends
    - Monthly payers: Sum of last 12 dividends
    - Annual payers: Last 1 dividend payment

    Args:
        ticker (str): Stock ticker symbol (e.g., "STWD", "DSU", "BXMT")

    Returns:
        float: Current dividend yield as percentage (e.g., 9.47 for 9.47%)
               Returns 0.0 for non-dividend paying stocks or on API errors

    Example:
        >>> yield_pct = fetch_current_dividend_yield("STWD")
        >>> print(f"STWD current yield: {yield_pct:.2f}%")
        STWD current yield: 9.47%

    Note:
        Results should closely match FMP quoted yields due to frequency-based 
        TTM calculation methodology.
    """
    try:
        end_month = (pd.Timestamp.today().to_period("M") - 1).to_timestamp("M")
        lookback_months = int(DIVIDEND_DEFAULTS.get("lookback_months", 12))
        start_month = end_month - pd.DateOffset(months=lookback_months - 1)

        div_df = fetch_dividend_history(ticker, start_month, end_month)
        if isinstance(div_df, pd.Series):
            # Ensure DataFrame form if cache returns a Series unexpectedly
            div_df = div_df.to_frame(name="adjDividend")
        if div_df is None or div_df.empty:
            return 0.0

        annual_dividends = pd.to_numeric(div_df.get("adjDividend", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()

        # Use month-end close aligned to end_month
        prices = fetch_monthly_close(ticker, None, end_month.date().isoformat())
        if prices is None or prices.dropna().empty:
            return 0.0
        current_price = float(prices.dropna().iloc[-1])
        if current_price <= 0:
            return 0.0

        if annual_dividends <= 0:
            return 0.0

        dividend_yield = (annual_dividends / current_price) * 100.0
        if dividend_yield > DIVIDEND_DATA_QUALITY_THRESHOLD * 100.0:
            from utils.logging import log_portfolio_operation
            log_portfolio_operation(
                "dividend_yield_data_quality_warning",
                {
                    "ticker": ticker,
                    "calculated_yield": dividend_yield,
                    "reason": "unusually_high_yield",
                    "threshold_pct": DIVIDEND_DATA_QUALITY_THRESHOLD * 100.0,
                },
                execution_time=0,
            )
            return 0.0

        return round(float(dividend_yield), 4)
    except Exception as e:
        from utils.logging import log_portfolio_operation
        log_portfolio_operation(
            "dividend_yield_calculation_failed",
            {
                "ticker": ticker,
                "error": str(e),
                "error_type": type(e).__name__
            },
            execution_time=0,
        )
        return 0.0

# ----------------------------------------------------------------------
#  RAM-cache wrapper  (add this at the very bottom of data_loader.py)
# ----------------------------------------------------------------------
import pandas as pd                                 # already imported above

# 1) private handle to the disk-cached version
_fetch_monthly_close_disk = fetch_monthly_close     
_fetch_monthly_treasury_rates_disk = fetch_monthly_treasury_rates

# 2) re-export the public name with an LRU layer
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def fetch_monthly_close(         # ← same name seen by callers
    ticker: str,
    start_date: str | None = None,
    end_date:   str | None = None,
) -> pd.Series:
    """
    RAM-cached → disk-cached → network price fetch.
    Same signature and behaviour as the original function.
    """
    # LOGGING: Add LRU cache layer logging
    # cache_info = fetch_monthly_close.cache_info()
    # log_performance_metric("lru_cache_fetch_monthly_close", cache_info.hits, cache_info.misses, details={"ticker": ticker, "cache_size": cache_info.currsize, "max_size": cache_info.maxsize})
    
    return _fetch_monthly_close_disk(ticker, start_date, end_date)


@lru_cache(maxsize=TREASURY_RATE_LRU_SIZE)
def fetch_monthly_treasury_rates(
    maturity: str = "month3",
    start_date: str | None = None,
    end_date:   str | None = None,
) -> pd.Series:
    """
    RAM-cached → disk-cached → network Treasury rate fetch.
    Same signature and behaviour as the original function.
    """
    # LOGGING: Add LRU cache layer logging for treasury rates
    # cache_info = fetch_monthly_treasury_rates.cache_info()
    # log_performance_metric("lru_cache_fetch_treasury_rates", cache_info.hits, cache_info.misses, details={"maturity": maturity, "cache_size": cache_info.currsize, "max_size": cache_info.maxsize})
    
    return _fetch_monthly_treasury_rates_disk(maturity, start_date, end_date)



# In[ ]:
