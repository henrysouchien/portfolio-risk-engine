#!/usr/bin/env python
# coding: utf-8

# In[1]:


# File: factor_utils.py

import requests
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import datetime
from typing import Optional, Union, List, Dict
from data_loader import fetch_monthly_close
from dotenv import load_dotenv
import os

# Load .env file before accessing environment variables
load_dotenv()

# Import logging decorators for factor analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_api_health
)

# Configuration
FMP_API_KEY = os.getenv("FMP_API_KEY")
API_KEY  = FMP_API_KEY
BASE_URL = "https://financialmodelingprep.com/stable"


def calc_monthly_returns(prices: pd.Series) -> pd.Series:
    """
    Compute percent-change monthly returns from price series.

    Args:
        prices (pd.Series): Month-end price series.

    Returns:
        pd.Series: Monthly % change returns, NaNs dropped.
    """
    prices = prices.ffill() 
    return prices.pct_change(fill_method=None).dropna()


def compute_volatility(returns: pd.Series) -> Dict[str, float]:
    """
    Calculate monthly and annualized volatility from a returns series.

    Args:
        returns (pd.Series): Series of periodic returns.

    Returns:
        dict: {
            "monthly_vol": float,  # standard deviation of returns
            "annual_vol":  float   # scaled by sqrt(12)
        }
    """
    vol_m = float(returns.std())
    vol_a = vol_m * np.sqrt(12)
    return {"monthly_vol": vol_m, "annual_vol": vol_a}


def compute_regression_metrics(df: pd.DataFrame) -> Dict[str, float]:
    """
    Run OLS regression of stock returns vs. market returns.

    Args:
        df (pd.DataFrame): DataFrame with columns ["stock", "market"].

    Returns:
        dict: {
            "beta":      float,  # slope coefficient
            "alpha":     float,  # intercept
            "r_squared": float,  # model R²
            "idio_vol_m":  float   # std deviation of residuals
        }
    """
    X     = sm.add_constant(df["market"])
    model = sm.OLS(df["stock"], X).fit()
    return {
        "beta":      float(model.params["market"]),
        "alpha":     float(model.params["const"]),
        "r_squared": float(model.rsquared),
        "idio_vol_m":  float(model.resid.std())
    }


@log_error_handling("high")
def fetch_peer_median_monthly_returns(
    tickers: List[str],
    start_date: Optional[Union[str, datetime]] = None,
    end_date:   Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Compute the cross-sectional median of peer tickers' monthly returns.

    Args:
        tickers (List[str]): List of peer ticker symbols.
        start_date (str|datetime, optional): Earliest date for fetch.
        end_date   (str|datetime, optional): Latest date for fetch.

    Returns:
        pd.Series: Median of monthly returns across peers.
                   Returns empty Series if no tickers provided.
    """
    # Handle empty ticker list
    if not tickers:
        return pd.Series(dtype=float, name='median_returns')
    
    series_list = []
    for t in tickers:
        prices = fetch_monthly_close(t, start_date=start_date, end_date=end_date)
        rets   = calc_monthly_returns(prices).rename(t)
        series_list.append(rets)
    df_peers = pd.concat(series_list, axis=1).dropna()
    return df_peers.median(axis=1)


def fetch_excess_return(
    etf_ticker: str,
    market_ticker: str = "SPY",
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Compute style-factor excess returns: ETF minus market, aligned by index.

    Returns:
        pd.Series: Excess monthly returns (etf - market), aligned on date.
    """
    etf_ret    = calc_monthly_returns(fetch_monthly_close(etf_ticker,    start_date, end_date))
    market_ret = calc_monthly_returns(fetch_monthly_close(market_ticker, start_date, end_date))

    # Force strict index alignment before subtraction
    common_idx = etf_ret.index.intersection(market_ret.index)
    etf_aligned    = etf_ret.loc[common_idx]
    market_aligned = market_ret.loc[common_idx]

    return etf_aligned - market_aligned

@log_error_handling("high")
def compute_factor_metrics(
    stock_returns: pd.Series,
    factor_dict: Dict[str, pd.Series]
) -> pd.DataFrame:
    """
    Runs independent single-factor regressions of stock returns vs. each factor.

    For each factor, calculates:
      • beta (cov(stock, factor) / var(factor))
      • R² (correlation squared)
      • idiosyncratic volatility (monthly residual std deviation)

    Args:
        stock_returns (pd.Series): Monthly stock returns (datetime index).
        factor_dict (Dict[str, pd.Series]): Dict of factor name to factor return series.

    Returns:
        pd.DataFrame: One row per factor, columns: beta, r_squared, idio_vol_m
    """
    # LOGGING: Add factor metrics calculation start logging
    # LOGGING: Add factor calculation timing
    # LOGGING: Add peer analysis logging
    # LOGGING: Add regression computation logging
    # LOGGING: Add data quality validation logging
    results = {}

    for name, factor_series in factor_dict.items():
        # Force exact alignment
        common_idx = stock_returns.index.intersection(factor_series.index)
        stock = stock_returns.loc[common_idx]
        factor = factor_series.loc[common_idx]

        if len(stock) < 2:
            continue  # Skip if not enough data

        # Calculate regression statistics
        cov = stock.cov(factor)
        var = factor.var()
        beta = cov / var
        alpha = stock.mean() - beta * factor.mean()
        resid = stock - (alpha + beta * factor)
        idio_vol_m = resid.std(ddof=1)
        r_squared = stock.corr(factor) ** 2

        results[name] = {
            "beta":        float(beta),
            "r_squared":   float(r_squared),
            "idio_vol_m":  float(idio_vol_m)
        }

    return pd.DataFrame(results).T  # One row per factor


# In[ ]:


# File: factor_utils.py

import pandas as pd
from typing import Dict

@log_error_handling("high")
def compute_stock_factor_betas(
    stock_ret: pd.Series,
    factor_rets: Dict[str, pd.Series]
) -> Dict[str, float]:
    """
    Wrapper that re-uses compute_factor_metrics to get betas for a single stock.

    Args
    ----
    stock_ret : pd.Series
        The stock’s return series, indexed by date.
    factor_rets : Dict[str, pd.Series]
        Mapping {factor_name: factor_return_series}.

    Returns
    -------
    Dict[str, float]
        {factor_name: beta} pulled straight from compute_factor_metrics.
    """
    # call the existing helper (must already be imported / defined in scope)
    df_metrics = compute_factor_metrics(stock_ret, factor_rets)

    # return only the β column as a plain dict
    return df_metrics["beta"].to_dict()

def calc_factor_vols(
    factor_dict: Dict[str, pd.Series],
    annualize: bool = True
) -> Dict[str, float]:
    """
    Return annualised σ for every factor series supplied.

    factor_dict  – {"market": Series, "momentum": Series, ...}
    """
    k = 12 ** 0.5 if annualize else 1.0
    return {name: float(series.std(ddof=1) * k) for name, series in factor_dict.items()}

def calc_weighted_factor_variance(
    weights: Dict[str, float],
    betas_df: pd.DataFrame,
    df_factor_vols: pd.DataFrame
) -> pd.DataFrame:
    """
    Weighted factor variance for each (asset, factor):

       w_i² · β_i,f² · σ_f²

    Args:
        weights (Dict[str, float]): Portfolio weights {"PCTY": 0.15, ...}
        betas_df (pd.DataFrame): DataFrame index=tickers, columns=factors, values=β
        df_factor_vols (pd.DataFrame): Factor volatilities DataFrame, same structure as betas_df

    Returns:
        pd.DataFrame: Weighted factor variance contributions, same shape as betas_df.
        
    Note:
        - NaN betas → 0.0
        - Missing factors → 0.0  
        - Asset mismatches → 0.0
    """
    # Handle empty inputs
    if not weights or betas_df.empty or df_factor_vols.empty:
        return pd.DataFrame(
            0.0,
            index=betas_df.index if not betas_df.empty else [],
            columns=betas_df.columns if not betas_df.empty else []
        )
    
    # Clean tables & fill NaNs with 0 (exact portfolio_risk.py pattern)
    df_factor_vols = df_factor_vols.fillna(0.0)
    betas_filled = betas_df.fillna(0.0)
    
    # Handle weights with asset safety (only addition to your pattern)
    w2 = pd.Series(weights).reindex(betas_df.index).fillna(0.0).pow(2)
    
    # Your proven calculation: w_i² β_i,f² σ_i,f²
    weighted_factor_var = betas_filled.pow(2) * df_factor_vols.pow(2)
    weighted_factor_var = weighted_factor_var.mul(w2, axis=0)
    
    return weighted_factor_var

