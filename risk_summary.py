#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# File: risk_summary.py

from datetime import datetime
import pandas as pd
from typing import Dict, Union

from data_loader import fetch_monthly_close
from factor_utils import (
    calc_monthly_returns,
    compute_volatility,
    compute_regression_metrics,
    compute_factor_metrics,
    fetch_excess_return,
    fetch_peer_median_monthly_returns
)

# Import logging decorators for risk summary analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)

@log_error_handling("high")
@log_portfolio_operation_decorator("single_stock_analysis")
@log_performance(2.0)
def get_stock_risk_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    benchmark: str = "SPY"
) -> Dict[str, Union[float, Dict[str, float]]]:
    """
    Pulls monthly prices between given dates, computes returns, vol, and regression metrics.
    Returns a dict:
      {
        "vol_metrics": {...},
        "risk_metrics": {...}
      }

    Args:
        ticker (str): Stock symbol.
        start_date (str or pd.Timestamp): Start of analysis window.
        end_date (str or pd.Timestamp): End of analysis window.
        benchmark (str): Benchmark ticker for regression (default: "SPY").
    """
    stock_prices  = fetch_monthly_close(ticker,    start_date=start_date, end_date=end_date)
    market_prices = fetch_monthly_close(benchmark, start_date=start_date, end_date=end_date)

    stock_ret  = calc_monthly_returns(stock_prices)
    market_ret = calc_monthly_returns(market_prices)

    df_ret = pd.DataFrame({
        "stock":  stock_ret,
        "market": market_ret
    }).dropna()

    vol_metrics  = compute_volatility(df_ret["stock"])
    risk_metrics = compute_regression_metrics(df_ret)

    return {
        "vol_metrics":  vol_metrics,
        "risk_metrics": risk_metrics
    }


# In[ ]:


from typing import List, Dict, Optional, Union
import pandas as pd

@log_error_handling("high")
@log_portfolio_operation_decorator("detailed_stock_factor_analysis")
@log_performance(3.0)
def get_detailed_stock_factor_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    factor_proxies: Dict[str, Union[str, List[str]]],
    market_ticker: str = "SPY"
) -> Dict[str, Union[pd.DataFrame, Dict[str, float]]]:
    """
    Computes full factor risk diagnostics for a stock over a given window,
    using specified ETF proxies and peer sets.

    Args:
        ticker (str): Stock ticker to analyze.
        start_date (str or Timestamp): Start date for analysis window.
        end_date (str or Timestamp): End date for analysis window.
        factor_proxies (dict): Mapping of factor name → ETF or peer list.
            Required keys: market, momentum, value, industry, subindustry
        market_ticker (str): Market benchmark ticker (for excess returns).

    Returns:
        dict:
            - vol_metrics: volatility stats
            - regression_metrics: beta, alpha, R², idio vol (market only)
            - factor_summary: DataFrame of beta / R² / idio vol per factor
    """
    stock_prices  = fetch_monthly_close(ticker, start_date=start_date, end_date=end_date)
    stock_returns = calc_monthly_returns(stock_prices)

    def align(series: pd.Series) -> pd.Series:
        return series.loc[stock_returns.index.intersection(series.index)]

    # Fetch and align all factor return series
    market_ret   = align(calc_monthly_returns(fetch_monthly_close(factor_proxies["market"], start_date, end_date)))
    momentum_ret = align(fetch_excess_return(factor_proxies["momentum"], market_ticker, start_date, end_date))
    value_ret    = align(fetch_excess_return(factor_proxies["value"], market_ticker, start_date, end_date))

    industry_ret = align(fetch_peer_median_monthly_returns(
        factor_proxies["industry"] if isinstance(factor_proxies["industry"], list)
        else [factor_proxies["industry"]],
        start_date, end_date
    ))

    subind_ret = align(fetch_peer_median_monthly_returns(
        factor_proxies["subindustry"] if isinstance(factor_proxies["subindustry"], list)
        else [factor_proxies["subindustry"]],
        start_date, end_date
    ))

    # Build combined factor dictionary
    factor_dict = {
        "market":      market_ret,
        "momentum":    momentum_ret,
        "value":       value_ret,
        "industry":    industry_ret,
        "subindustry": subind_ret
    }

    # Regression vs market only
    df_reg = pd.DataFrame({"stock": stock_returns, "market": market_ret}).dropna()

    return {
        "vol_metrics": compute_volatility(df_reg["stock"]),
        "regression_metrics": compute_regression_metrics(df_reg),
        "factor_summary": compute_factor_metrics(stock_returns, factor_dict)
    }

