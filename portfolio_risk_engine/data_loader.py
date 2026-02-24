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
from datetime import datetime
from pathlib import Path
from typing import Iterable, Callable, Union, Optional
import hashlib
import pandas as pd
from pandas.errors import EmptyDataError, ParserError

# Add logging decorator imports
from portfolio_risk_engine._logging import (
    log_portfolio_operation,
    log_errors,
)
from portfolio_risk_engine.config import (
    DIVIDEND_LRU_SIZE,
    DIVIDEND_DATA_QUALITY_THRESHOLD,
)
from portfolio_risk_engine._ticker import select_fmp_symbol
from portfolio_risk_engine.config import DIVIDEND_DEFAULTS
from portfolio_risk_engine.providers import get_price_provider

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


@log_errors("high")
def fetch_monthly_close(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date:   Optional[Union[str, datetime]] = None,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
) -> pd.Series:
    """
    Fetch month-end closing prices for a given ticker from FMP.

    Uses the `/stable/historical-price-eod/full` endpoint with optional
    `from` and `to` parameters, then resamples to month-end.

    Args:
        ticker (str):       Stock or ETF symbol (display/original).
        start_date (str|datetime, optional): Earliest date (inclusive).
        end_date   (str|datetime, optional): Latest date (inclusive).
        fmp_ticker (str, optional): FMP-compatible symbol override.
        fmp_ticker_map (dict, optional): Mapping of ticker -> fmp_ticker.

    Returns:
        pd.Series: Month-end close prices indexed by date.
    """
    return get_price_provider().fetch_monthly_close(
        ticker,
        start_date,
        end_date,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )


@log_errors("high")
def fetch_monthly_total_return_price(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
) -> pd.Series:
    """
    Fetch dividend-adjusted month-end prices (total return) from FMP.

    Primary: /historical-price-eod/dividend-adjusted (adjClose)
    Fallback: /historical-price-eod/full (close) – flagged as price-only via name suffix.

    Args:
        ticker (str):       Stock or ETF symbol (display/original).
        start_date (str|datetime, optional): Earliest date (inclusive).
        end_date   (str|datetime, optional): Latest date (inclusive).
        fmp_ticker (str, optional): FMP-compatible symbol override.
        fmp_ticker_map (dict, optional): Mapping of ticker -> fmp_ticker.
    """
    return get_price_provider().fetch_monthly_total_return_price(
        ticker,
        start_date,
        end_date,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )




@log_errors("high")
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
    return get_price_provider().fetch_monthly_treasury_rates(
        maturity,
        start_date,
        end_date,
    )


# ── Dividends (monthly-stable cache) ─────────────────────────────────────────

@log_errors("high")
def fetch_dividend_history(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
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
        fmp_ticker (str, optional): FMP-compatible symbol override.
        fmp_ticker_map (dict, optional): Mapping of ticker -> fmp_ticker.

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
    return get_price_provider().fetch_dividend_history(
        ticker,
        start_date,
        end_date,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )


from functools import lru_cache

@lru_cache(maxsize=DIVIDEND_LRU_SIZE)
def _fetch_current_dividend_yield_lru(fmp_symbol: str) -> float:
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
        fmp_symbol (str): FMP-compatible ticker symbol (e.g., "STWD", "DSU", "BXMT")

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

        div_df = fetch_dividend_history(
            fmp_symbol,
            start_month,
            end_month,
            fmp_ticker=fmp_symbol,
        )
        if isinstance(div_df, pd.Series):
            # Ensure DataFrame form if cache returns a Series unexpectedly
            div_df = div_df.to_frame(name="adjDividend")
        if div_df is None or div_df.empty:
            return 0.0

        annual_dividends = pd.to_numeric(div_df.get("adjDividend", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()

        # Use month-end close aligned to end_month
        prices = fetch_monthly_close(
            fmp_symbol,
            None,
            end_month.date().isoformat(),
            fmp_ticker=fmp_symbol,
        )
        if prices is None or prices.dropna().empty:
            return 0.0
        current_price = float(prices.dropna().iloc[-1])
        if current_price <= 0:
            return 0.0

        if annual_dividends <= 0:
            return 0.0

        dividend_yield = (annual_dividends / current_price) * 100.0
        if dividend_yield > DIVIDEND_DATA_QUALITY_THRESHOLD * 100.0:
            from portfolio_risk_engine._logging import log_portfolio_operation
            log_portfolio_operation(
                "dividend_yield_data_quality_warning",
                {
                "ticker": fmp_symbol,
                "calculated_yield": dividend_yield,
                "reason": "unusually_high_yield",
                "threshold_pct": DIVIDEND_DATA_QUALITY_THRESHOLD * 100.0,
                },
                execution_time=0,
            )
            return 0.0

        return round(float(dividend_yield), 4)
    except Exception as e:
        from portfolio_risk_engine._logging import log_portfolio_operation
        log_portfolio_operation(
            "dividend_yield_calculation_failed",
            {
                "ticker": fmp_symbol,
                "error": str(e),
                "error_type": type(e).__name__
            },
            execution_time=0,
        )
        return 0.0


def fetch_current_dividend_yield(
    ticker: str,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict[str, str]] = None,
) -> float:
    """
    Wrapper that resolves FMP symbol before hitting the cached dividend yield.
    """
    fmp_symbol = select_fmp_symbol(
        ticker,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )
    try:
        return float(
            get_price_provider().fetch_current_dividend_yield(
                fmp_symbol,
                fmp_ticker=fmp_symbol,
            )
        )
    except Exception:
        return _fetch_current_dividend_yield_lru(fmp_symbol)
