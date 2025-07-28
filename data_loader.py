#!/usr/bin/env python
# coding: utf-8

# In[1]:


# File: data_loader.py

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
    log_error_handling
)

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

# ----------------------------------------------------------------------
#  RAM-cache wrapper  (add this at the very bottom of data_loader.py)
# ----------------------------------------------------------------------
from functools import lru_cache
import pandas as pd                                 # already imported above

# 1) private handle to the disk-cached version
_fetch_monthly_close_disk = fetch_monthly_close     
_fetch_monthly_treasury_rates_disk = fetch_monthly_treasury_rates

# 2) re-export the public name with an LRU layer
@lru_cache(maxsize=256)          # tune size to taste
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


@lru_cache(maxsize=64)          # smaller cache for Treasury rates
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




