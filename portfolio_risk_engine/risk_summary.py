#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# File: risk_summary.py

from datetime import datetime
import pandas as pd
from typing import Dict, Union, Optional

from core.realized_performance.nav import _safe_treasury_rate
from portfolio_risk_engine.data_loader import fetch_monthly_close
from portfolio_risk_engine.factor_utils import (
    calc_monthly_returns,
    compute_volatility,
    compute_regression_metrics,
    compute_factor_metrics,
    compute_multifactor_betas,
    fetch_excess_return,
    fetch_peer_median_monthly_returns
)
from portfolio_risk_engine.portfolio_risk import compute_stock_performance_metrics

def get_stock_risk_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    benchmark: str = "SPY",
    ticker_alias_map: Optional[Dict[str, str]] = None,
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
        ticker_alias_map=ticker_alias_map,
    )
    market_prices = fetch_monthly_close(
        benchmark,
        start_date=start_date,
        end_date=end_date,
        ticker_alias_map=ticker_alias_map,
    )

    stock_ret  = calc_monthly_returns(stock_prices)
    market_ret = calc_monthly_returns(market_prices)

    df_ret = pd.DataFrame({
        "stock":  stock_ret,
        "market": market_ret
    }).dropna()

    vol_metrics  = compute_volatility(df_ret["stock"])
    risk_metrics = compute_regression_metrics(df_ret)

    risk_free_rate = _safe_treasury_rate(
        pd.Timestamp(start_date).to_pydatetime(),
        pd.Timestamp(end_date).to_pydatetime(),
    )
    stock_perf = compute_stock_performance_metrics(
        pd.DataFrame({"stock": df_ret["stock"]}),
        risk_free_rate=risk_free_rate,
        start_date=str(start_date),
        end_date=str(end_date),
    )
    if "stock" in stock_perf.index:
        vol_metrics["sharpe_ratio"] = float(stock_perf.loc["stock", "Sharpe"])
        vol_metrics["sortino_ratio"] = float(stock_perf.loc["stock", "Sortino"])
        vol_metrics["max_drawdown"] = float(stock_perf.loc["stock", "Max Drawdown"])

    return {
        "vol_metrics":  vol_metrics,
        "risk_metrics": risk_metrics
    }


# In[ ]:


from typing import List, Dict, Optional, Union
import pandas as pd


def _compute_variance_attribution(
    stock_returns: pd.Series,
    factor_df: pd.DataFrame,
    multifactor_stats: Dict[str, object],
) -> Optional[Dict[str, float]]:
    """Compute exact additive variance attribution from a joint OLS fit."""
    betas = multifactor_stats.get("betas")
    resid = multifactor_stats.get("resid")

    if not isinstance(betas, dict) or not betas:
        return None
    if not isinstance(resid, pd.Series) or resid.empty:
        return None

    aligned = pd.concat([stock_returns, factor_df], axis=1).dropna()
    if aligned.empty:
        return None

    y = aligned.iloc[:, 0]
    aligned_resid = resid.reindex(y.index)
    if aligned_resid.isna().any():
        return None

    stock_var = y.var()
    if pd.isna(stock_var) or stock_var <= 0:
        return None

    fitted_values = y - aligned_resid
    variance_attribution: Dict[str, float] = {}

    for factor_name in factor_df.columns:
        beta_value = betas.get(factor_name, 0.0)
        try:
            beta = float(beta_value)
        except (TypeError, ValueError):
            beta = 0.0
        cov_with_fitted = aligned[factor_name].cov(fitted_values)
        contribution = (beta * cov_with_fitted) / stock_var
        variance_attribution[factor_name] = float(contribution)

    variance_attribution["idiosyncratic"] = float(aligned_resid.var() / stock_var)
    return variance_attribution

def get_detailed_stock_factor_profile(
    ticker: str,
    start_date: Union[str, pd.Timestamp],
    end_date: Union[str, pd.Timestamp],
    factor_proxies: Dict[str, Union[str, List[str]]],
    market_ticker: str = "SPY",
    ticker_alias_map: Optional[Dict[str, str]] = None,
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
        ticker_alias_map=ticker_alias_map,
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
            ticker_alias_map=ticker_alias_map,
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
            ticker_alias_map=ticker_alias_map,
        ))

    value_proxy = factor_proxies.get("value")
    if value_proxy:
        factor_dict["value"] = align(fetch_excess_return(
            value_proxy,
            market_ticker,
            start_date,
            end_date,
            ticker_alias_map=ticker_alias_map,
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
            ticker_alias_map=ticker_alias_map,
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
            ticker_alias_map=ticker_alias_map,
        ))

    # Regression vs market only
    df_reg = pd.DataFrame({"stock": stock_returns, "market": market_ret}).dropna()
    vol_metrics = compute_volatility(df_reg["stock"])
    try:
        stock_perf = compute_stock_performance_metrics(
            pd.DataFrame({"stock": df_reg["stock"]}),
            risk_free_rate=0.04,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        if "stock" in stock_perf.index:
            vol_metrics["sharpe_ratio"] = float(stock_perf.loc["stock", "Sharpe"])
            vol_metrics["sortino_ratio"] = float(stock_perf.loc["stock", "Sortino"])
            vol_metrics["max_drawdown"] = float(stock_perf.loc["stock", "Max Drawdown"])
    except Exception:
        pass

    factor_df = pd.DataFrame(factor_dict)
    multifactor_stats = compute_multifactor_betas(stock_returns, factor_df)
    variance_attribution = _compute_variance_attribution(
        stock_returns,
        factor_df,
        multifactor_stats,
    )

    profile = {
        "vol_metrics": vol_metrics,
        "regression_metrics": compute_regression_metrics(df_reg),
        "factor_summary": compute_factor_metrics(stock_returns, factor_dict),
    }
    if variance_attribution is not None:
        profile["variance_attribution"] = variance_attribution
    return profile
