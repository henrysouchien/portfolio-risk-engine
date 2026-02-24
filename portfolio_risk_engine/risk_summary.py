#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# File: risk_summary.py

from datetime import datetime
import pandas as pd
from typing import Dict, Union, Optional

from portfolio_risk_engine.data_loader import fetch_monthly_close
from portfolio_risk_engine.factor_utils import (
    calc_monthly_returns,
    compute_volatility,
    compute_regression_metrics,
    compute_factor_metrics,
    fetch_excess_return,
    fetch_peer_median_monthly_returns
)
from portfolio_risk_engine.portfolio_risk import compute_stock_performance_metrics

def get_stock_risk_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    benchmark: str = "SPY",
    fmp_ticker_map: Optional[Dict[str, str]] = None,
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
    stock_prices  = fetch_monthly_close(
        ticker,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
    )
    market_prices = fetch_monthly_close(
        benchmark,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
    )

    stock_ret  = calc_monthly_returns(stock_prices)
    market_ret = calc_monthly_returns(market_prices)

    df_ret = pd.DataFrame({
        "stock":  stock_ret,
        "market": market_ret
    }).dropna()

    vol_metrics  = compute_volatility(df_ret["stock"])
    risk_metrics = compute_regression_metrics(df_ret)

    stock_perf = compute_stock_performance_metrics(
        pd.DataFrame({"stock": df_ret["stock"]}),
        risk_free_rate=0.04,
        start_date=str(start_date),
        end_date=str(end_date),
    )
    if "stock" in stock_perf.index:
        vol_metrics["sharpe_ratio"] = float(stock_perf.loc["stock", "Sharpe"])
        vol_metrics["sortino_ratio"] = float(stock_perf.loc["stock", "Sortino"])

    return {
        "vol_metrics":  vol_metrics,
        "risk_metrics": risk_metrics
    }


# In[ ]:


from typing import List, Dict, Optional, Union
import pandas as pd

def get_detailed_stock_factor_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    factor_proxies: Dict[str, Union[str, List[str]]],
    market_ticker: str = "SPY",
    fmp_ticker_map: Optional[Dict[str, str]] = None,
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
    stock_prices = fetch_monthly_close(
        ticker,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
    )
    stock_returns = calc_monthly_returns(stock_prices)

    def align(series: pd.Series) -> pd.Series:
        return series.loc[stock_returns.index.intersection(series.index)]

    # Fetch and align factor return series. Be defensive here so callers with
    # partial factor maps degrade gracefully instead of raising KeyError.
    market_proxy = factor_proxies.get("market") or market_ticker
    market_ret = align(calc_monthly_returns(
        fetch_monthly_close(
            market_proxy,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
    ))

    factor_dict = {"market": market_ret}

    momentum_proxy = factor_proxies.get("momentum")
    if momentum_proxy:
        factor_dict["momentum"] = align(fetch_excess_return(
            momentum_proxy,
            market_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        ))

    value_proxy = factor_proxies.get("value")
    if value_proxy:
        factor_dict["value"] = align(fetch_excess_return(
            value_proxy,
            market_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        ))

    industry_proxy = factor_proxies.get("industry")
    if industry_proxy:
        industry_universe = (
            industry_proxy if isinstance(industry_proxy, list) else [industry_proxy]
        )
        factor_dict["industry"] = align(fetch_peer_median_monthly_returns(
            industry_universe,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        ))

    subindustry_proxy = factor_proxies.get("subindustry")
    if subindustry_proxy:
        subindustry_universe = (
            subindustry_proxy if isinstance(subindustry_proxy, list) else [subindustry_proxy]
        )
        factor_dict["subindustry"] = align(fetch_peer_median_monthly_returns(
            subindustry_universe,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        ))

    # Regression vs market only
    df_reg = pd.DataFrame({"stock": stock_returns, "market": market_ret}).dropna()

    return {
        "vol_metrics": compute_volatility(df_reg["stock"]),
        "regression_metrics": compute_regression_metrics(df_reg),
        "factor_summary": compute_factor_metrics(stock_returns, factor_dict)
    }
