#!/usr/bin/env python
# coding: utf-8

# In[1]:


# File: factor_utils.py
"""
Factor utilities and helpers.

Key capabilities (updated):
- Total-return preference: All return series fetched via this module now prefer
  dividend-adjusted (total return) prices when available, with a safe fallback
  to close-only series.
- Treasury rate integration: Helpers to aggregate monthly Treasury yield levels
  and transform them into Δy (changes in yield) in decimal units for key‑rate
  analysis.
- Multifactor regression (HAC): Multivariate OLS with Newey–West (HAC) standard
  errors for key‑rate betas, including diagnostics such as adjusted R²,
  condition number, and VIF (variance inflation factors) to assess
  multicollinearity among rate factors.

Notes:
- Δy scaling: Inputs are in percentages; prepare_rate_factors converts to
  decimal (0.01 for 1%) before differencing. Regression betas are thus already
  in “per 1.00 change in yield” terms (a +1% change is 0.01 in the regressor).
- TR preference does not change shapes or indices; it only improves return
  accuracy by accounting for distributions.
"""

import requests
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import datetime
from typing import Optional, Union, List, Dict, Any
from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_total_return_price
from dotenv import load_dotenv
import os

# Load .env file before accessing environment variables
load_dotenv()

# Import logging decorators for factor analysis
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
)

# Configuration
FMP_API_KEY = os.getenv("FMP_API_KEY")
API_KEY  = FMP_API_KEY
BASE_URL = "https://financialmodelingprep.com/stable"


def calc_monthly_returns(prices: pd.Series) -> pd.Series:
    """
    Compute percent-change monthly returns from a month-end price series.

    Args:
        prices (pd.Series): Month-end price series.

    Returns:
        pd.Series: Monthly percent-change returns with NaNs dropped.
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


@log_errors("high")
def fetch_peer_median_monthly_returns(
    tickers: List[str],
    start_date: Optional[Union[str, datetime]] = None,
    end_date:   Optional[Union[str, datetime]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> pd.Series:
    """
    Compute the cross-sectional median of peer tickers' monthly returns.

    Uses total-return (dividend-adjusted) prices when available for improved
    accuracy, with a safe fallback to close-only prices.
    
    Robustly handles individual peer failures by dropping peers with no data
    overlap in the analysis window, but continuing with remaining good peers
    instead of failing entirely.

    Args:
        tickers (List[str]): List of peer ticker symbols.
        start_date (str|datetime, optional): Earliest date for fetch.
        end_date   (str|datetime, optional): Latest date for fetch.

    Returns:
        pd.Series: Median of monthly returns across peers.
                   Returns empty Series if no tickers provided or all peers fail.
    """
    # Handle empty ticker list
    if not tickers:
        return pd.Series(dtype=float, name='median_returns')
    
    from portfolio_risk_engine._logging import log_portfolio_operation
    
    valid_series = []
    dropped_peers = []
    
    for ticker in tickers:
        try:
            # Prefer total-return prices for peers
            try:
                prices = fetch_monthly_total_return_price(
                    ticker,
                    start_date=start_date,
                    end_date=end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
            except Exception:
                prices = fetch_monthly_close(
                    ticker,
                    start_date=start_date,
                    end_date=end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
                
            returns = calc_monthly_returns(prices)
            
            # Filter returns to analysis window to check for actual data overlap
            if start_date and end_date:
                analysis_start = pd.to_datetime(start_date)
                analysis_end = pd.to_datetime(end_date)
                windowed_returns = returns.loc[analysis_start:analysis_end]
            else:
                windowed_returns = returns
            
            # Check for actual data overlap in the analysis window using centralized threshold
            from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
            min_overlap = DATA_QUALITY_THRESHOLDS["min_peer_overlap_observations"]
            
            if len(windowed_returns) >= min_overlap:  # Has sufficient data overlap in analysis window
                valid_series.append(returns.rename(ticker))  # Use full returns for median calc
            else:
                dropped_peers.append(ticker)
                log_portfolio_operation(
                    "peer_no_overlap",
                    {"ticker": ticker, "total_obs": len(returns), "window_obs": len(windowed_returns)},
                    execution_time=0
                )
                
        except Exception as e:
            dropped_peers.append(ticker)
            log_portfolio_operation(
                "peer_fetch_failed",
                {"ticker": ticker, "error": str(e)},
                execution_time=0
            )
    
    # Log summary of peer filtering
    if dropped_peers:
        log_portfolio_operation(
            "peer_filtering_summary",
            {
                "total_peers": len(tickers),
                "valid_peers": len(valid_series), 
                "dropped_peers": len(dropped_peers),
                "dropped_tickers": dropped_peers[:5]  # Log first 5 to avoid spam
            },
            execution_time=0
        )
    
    if valid_series:
        # Calculate median with remaining good peers, allowing pandas to handle NaNs
        df_peers = pd.concat(valid_series, axis=1)
        return df_peers.median(axis=1, skipna=True)
    else:
        # All peers failed
        log_portfolio_operation(
            "peer_all_failed",
            {"attempted_peers": len(tickers)},
            execution_time=0
        )
        return pd.Series(dtype=float, name='median_returns')


def fetch_excess_return(
    etf_ticker: str,
    market_ticker: str = "SPY",
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> pd.Series:
    """
    Compute style-factor excess returns: ETF minus market, aligned by index.

    Uses total-return (dividend-adjusted) prices when available for both legs,
    with a safe fallback to close-only prices.

    Returns:
        pd.Series: Excess monthly returns (etf - market), aligned on date.
    """
    if not market_ticker:
        raise ValueError(
            f"Cannot compute excess return for '{etf_ticker}': "
            f"market_ticker is {market_ticker!r}. "
            f"Ensure a 'market' proxy (e.g. 'SPY') is set in factor proxies."
        )
    # Prefer total-return prices for both ETF and market; fallback to close-only
    try:
        etf_prices = fetch_monthly_total_return_price(
            etf_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
    except Exception:
        etf_prices = fetch_monthly_close(
            etf_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
    try:
        mkt_prices = fetch_monthly_total_return_price(
            market_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
    except Exception:
        mkt_prices = fetch_monthly_close(
            market_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )

    etf_ret    = calc_monthly_returns(etf_prices)
    market_ret = calc_monthly_returns(mkt_prices)

    # Force strict index alignment before subtraction
    common_idx = etf_ret.index.intersection(market_ret.index)
    etf_aligned    = etf_ret.loc[common_idx]
    market_aligned = market_ret.loc[common_idx]

    return etf_aligned - market_aligned

@log_errors("high")
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

        from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
        min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_regression"]
        
        if len(stock) < min_obs:
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

@log_errors("high")
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


# (key‑rate helpers intentionally omitted pending architecture review)

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


# =========================
# Rate factor functionality
# =========================

@log_errors("medium")
@log_timing(1.0)
def prepare_rate_factors(
    yields_levels: pd.DataFrame,
    keys: Optional[List[str]] = None,
    scale: str = 'pp'
) -> pd.DataFrame:
    """
    Convert Treasury yield levels to Δy in DECIMAL by maturity.

    Inputs are percentage levels (e.g., 4.5 for 4.5%).
    Output columns named by rate factor keys (e.g., UST2Y, UST5Y) containing
    period-over-period differences in decimal (0.01 per 1 percentage point).

    Args:
        yields_levels: DataFrame with month-end yield levels in percentage units.
        keys: Optional list of desired factor keys; defaults to settings.
        scale: 'pp' to convert % to decimal first; 'decimal' if already decimal.

    Returns:
        DataFrame of Δy in decimal with aligned index, NaNs dropped.
    """
    from portfolio_risk_engine.config import RATE_FACTOR_CONFIG

    if keys is None:
        keys = RATE_FACTOR_CONFIG.get("default_maturities", ["UST2Y", "UST5Y", "UST10Y", "UST30Y"])
    colmap = RATE_FACTOR_CONFIG.get("treasury_mapping", {
        "UST2Y": "year2", "UST5Y": "year5", "UST10Y": "year10", "UST30Y": "year30"
    })

    out: Dict[str, pd.Series] = {}
    for k in keys:
        src = colmap.get(k)
        if not src or src not in yields_levels.columns:
            out[k] = pd.Series(dtype=float)
            continue

        series = yields_levels[src]
        dec = (series / 100.0) if scale == 'pp' else series
        out[k] = dec.sort_index().diff()

    df = pd.DataFrame(out)
    return df.dropna(how="any")


@log_errors("medium")
@log_timing(1.5)
def fetch_monthly_treasury_yield_levels(
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None
) -> pd.DataFrame:
    """
    Aggregate monthly Treasury yield levels (percentages) for configured maturities.

    Uses existing data_loader.fetch_monthly_treasury_rates for each maturity name.

    Returns:
        DataFrame with columns named by maturity names (e.g., year2, year5, ...)
        containing month-end yield levels (percentages), aligned across maturities
        and with NaN rows dropped.
    """
    from portfolio_risk_engine.data_loader import fetch_monthly_treasury_rates
    from portfolio_risk_engine.config import RATE_FACTOR_CONFIG
    from portfolio_risk_engine._logging import log_portfolio_operation

    treasury_mapping = RATE_FACTOR_CONFIG.get("treasury_mapping", {
        "UST2Y": "year2", "UST5Y": "year5", "UST10Y": "year10", "UST30Y": "year30"
    })

    yield_series: Dict[str, pd.Series] = {}
    for _, maturity_name in treasury_mapping.items():
        try:
            s = fetch_monthly_treasury_rates(maturity_name, start_date, end_date)
            yield_series[maturity_name] = s
        except Exception as e:
            log_portfolio_operation(
                "treasury_yield_fetch_failed",
                {"maturity": maturity_name, "error": str(e)},
                execution_time=0
            )

    if not yield_series:
        raise ValueError("No Treasury yield data available for configured maturities")

    min_required = RATE_FACTOR_CONFIG.get("min_required_maturities", 2)
    if len(yield_series) < min_required:
        log_portfolio_operation(
            "treasury_yield_insufficient",
            {"available": len(yield_series), "required": min_required},
            execution_time=0
        )

    df = pd.DataFrame(yield_series).dropna()
    return df


@log_errors("medium")
def compute_multifactor_betas(
    stock_returns: pd.Series,
    factor_df: pd.DataFrame,
    hac_lags: int = 3
) -> Dict[str, Any]:
    """
    Multivariate OLS regression with HAC (Newey–West) standard errors.

    Returns per-factor betas from a single multivariate regression along with
    diagnostics (adjusted R², t/p/std_err, condition number, and VIFs). Use for
    key‑rate vector regressions where factors may be correlated.
    """
    aligned = pd.concat([stock_returns, factor_df], axis=1).dropna()
    # Require minimum observations for meaningful regression using centralized threshold
    from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
    min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_regression"]
    
    if aligned.empty or len(aligned) < min_obs:
        return {
            'betas': {}, 'alpha': 0.0, 'r2': 0.0, 'r2_adj': 0.0,
            't': {}, 'p': {}, 'std_err': {}, 'resid': pd.Series(dtype=float),
            'vif': {}, 'cond_number': None
        }

    y = aligned.iloc[:, 0]
    X = sm.add_constant(aligned.iloc[:, 1:])

    try:
        model = sm.OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': hac_lags})
    except Exception:
        model = sm.OLS(y, X).fit()

    factor_names = aligned.columns[1:].tolist()
    betas = {name: float(model.params.get(name, 0.0)) for name in factor_names}

    try:
        cond_number = float(np.linalg.cond(X.values))
    except Exception:
        cond_number = None

    # VIF diagnostics for multicollinearity among factors
    def _compute_vif(factors: pd.DataFrame) -> Dict[str, float]:
        Xf = factors.dropna().copy()
        if Xf.empty or Xf.shape[1] < 2:
            return {c: 1.0 for c in factors.columns}
        std = Xf.std(ddof=1)
        keep = std[std > 1e-12].index.tolist()
        Xf = Xf[keep]
        if Xf.shape[1] < 2:
            return {c: 1.0 for c in factors.columns}
        Z = (Xf - Xf.mean()) / Xf.std(ddof=1)
        try:
            R = Z.corr().values
            Rinv = np.linalg.pinv(R)
            diag = np.diag(Rinv)
            return {col: float(diag[i]) for i, col in enumerate(Z.columns)}
        except Exception:
            vifs: Dict[str, float] = {}
            for col in Z.columns:
                yv = Z[col]
                Xv = sm.add_constant(Z.drop(columns=[col]))
                try:
                    r2v = sm.OLS(yv, Xv).fit().rsquared
                    vifs[col] = float(1.0 / max(1e-8, (1.0 - r2v)))
                except Exception:
                    vifs[col] = float('inf')
            return vifs

    vifs = _compute_vif(aligned.iloc[:, 1:])

    stats: Dict[str, Any] = {
        'betas': betas,
        'alpha': float(model.params.get('const', 0.0)),
        'r2': float(model.rsquared),
        'r2_adj': float(model.rsquared_adj),
        't': {f: float(model.tvalues.get(f, 0.0)) for f in factor_names},
        'p': {f: float(model.pvalues.get(f, 1.0)) for f in factor_names},
        'std_err': {f: float(model.bse.get(f, 0.0)) for f in factor_names},
        'resid': model.resid,
        'vif': vifs,
        'cond_number': cond_number,
    }
    return stats
