#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# File: portfolio_risk.py
"""
Portfolio risk analysis core with comprehensive performance and dividend analysis.

This module provides the complete portfolio analysis engine, including risk metrics,
performance analysis, factor exposures, and comprehensive dividend yield calculations.
Integrates multiple data sources and analytical methodologies for institutional-grade
portfolio management and risk assessment.

Core Capabilities:
- **Risk Analysis**: Comprehensive portfolio risk metrics and factor decomposition
- **Performance Analysis**: Total return calculations with benchmark comparisons  
 - **Dividend Analysis**: Current-yield (TTM adjDividend / month-end price) calculations and coverage
- **Factor Integration**: Multi-factor risk models with interest rate sensitivity
- **Total Return Methodology**: Preference for dividend-adjusted prices with fallbacks

Key Updates and Features:
- **Total-Return Adoption**: All asset and factor return series prefer dividend-
  adjusted (total return) prices where available, with safe fallback to close prices
- **Interest Rate Factor Integration**: Empirical key-rate regression against
  monthly Treasury yield changes (2y/5y/10y/30y), aggregated to single 'interest_rate'
  factor with comprehensive diagnostics (adj-R², VIF, condition number)
- **Dividend Yield Integration**: Trailing-12-month (TTM) adjDividend / month-end price
  integrated into performance analysis with portfolio-level yield aggregation and coverage metrics
- **Centralized Analysis Framework**: Risk, performance, and dividend computations share
  consistent date windows and month-end frequency for analytical consistency
- **Advanced Caching**: LRU cache with bond mask and version tokens to segregate
  analyses with/without rate factor injection and dividend calculations

Dividend Analysis Integration:
- Portfolio-weighted dividend yield using current-yield (TTM) methodology
- Individual position dividend contributions and data coverage metrics
- Top dividend contributors ranked by dollar contribution amounts
- Data quality assessment including coverage by count and portfolio weight
- Seamless integration with performance analysis for comprehensive income analysis
"""

import pandas as pd
import numpy as np
import statsmodels.api as sm
from typing import Dict, Optional, List, Union, Any
import functools
import hashlib
import json


from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_total_return_price, fetch_current_dividend_yield
from portfolio_risk_engine.factor_utils import (
    calc_monthly_returns,
    fetch_excess_return,
    fetch_peer_median_monthly_returns,
    compute_stock_factor_betas,
    calc_weighted_factor_variance,
    prepare_rate_factors,
    compute_multifactor_betas,
    fetch_monthly_treasury_yield_levels,
)

from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS

# Import logging decorators for portfolio analysis
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
)

def normalize_weights(weights: Dict[str, float], normalize: Optional[bool] = None) -> Dict[str, float]:
    """
    Normalize weights to gross exposure (sum of absolute values = 1).
    
    This preserves the economic meaning of positions (long stays long, short stays short)
    while normalizing to traditional portfolio scaling where the sum of all absolute 
    position sizes equals 100%.
    
    Args:
        weights: Dictionary of ticker -> weight
        normalize: If True, normalize to gross exposure. If False, return as-is.
                  If None (default), uses global setting from PORTFOLIO_DEFAULTS.
    
    Returns:
        Dictionary of normalized weights
    """
    if normalize is None:
        normalize = PORTFOLIO_DEFAULTS.get("normalize_weights", True)
    
    if not normalize:
        return weights
    total = sum(abs(w) for w in weights.values())
    if total == 0:
        raise ValueError("Sum of absolute weights is zero, cannot normalize.")
    # Normalize to gross exposure (sum of absolute values)
    return {t: w / total for t, w in weights.items()}

def compute_portfolio_returns(
    returns: pd.DataFrame,
    weights: Dict[str, float]
) -> pd.Series:
    """
    Given a DataFrame of individual asset returns (columns = tickers)
    and a dict of weights, compute the weighted portfolio return series.
    """
    w = normalize_weights(weights)
    # align columns and weights
    aligned = returns[list(w.keys())].dropna()
    weight_vec = np.array([w[t] for t in aligned.columns])
    # dot product row-wise
    port_ret = aligned.values.dot(weight_vec)
    return pd.Series(port_ret, index=aligned.index, name="portfolio")

def compute_covariance_matrix(
    returns: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute the sample covariance matrix of asset returns.
    """
    return returns.cov()

def compute_correlation_matrix(
    returns: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute the sample correlation matrix of asset returns.

    Args:
        returns (pd.DataFrame): DataFrame where each column is an asset's return series.

    Returns:
        pd.DataFrame: Correlation matrix between assets.
    """
    return returns.corr()

@log_errors("high")
@log_timing(1.0)
def compute_portfolio_volatility(
    weights: Dict[str, float],
    cov_matrix: pd.DataFrame
) -> float:
    """
    Compute portfolio volatility = sqrt(w^T Σ w).
    """
    w = normalize_weights(weights)
    w_vec = np.array([w[t] for t in cov_matrix.index])
    var_p = float(w_vec.T.dot(cov_matrix.values).dot(w_vec))
    return np.sqrt(var_p)

@log_errors("high")
@log_timing(1.0)
def compute_risk_contributions(
    weights: Dict[str, float],
    cov_matrix: pd.DataFrame
) -> pd.Series:
    """
    Compute each asset’s risk contribution to total portfolio volatility.
    RC_i = w_i * (Σ w)_i / σ_p
    Returns a Series indexed by ticker.
    """
    w = normalize_weights(weights)
    w_vec = np.array([w[t] for t in cov_matrix.index])
    sigma_p = compute_portfolio_volatility(weights, cov_matrix)
    # marginal contributions = (Σ w)_i
    marg = cov_matrix.values.dot(w_vec)
    rc = w_vec * marg / sigma_p
    return pd.Series(rc, index=cov_matrix.index, name="risk_contrib")

def compute_herfindahl(
    weights: Dict[str, float]
) -> float:
    """
    Compute the Herfindahl index = sum(w_i^2).
    Indicates portfolio concentration (0 = fully diversified, 1 = single asset).
    """
    w = normalize_weights(weights)
    return float(sum([w_i ** 2 for w_i in w.values()]))

# Example usage snippet (to paste in your notebook):
#
# import pandas as pd
# from portfolio_risk_engine.portfolio_risk import (
#     compute_portfolio_returns,
#     compute_covariance_matrix,
#     compute_portfolio_volatility,
#     compute_risk_contributions,
#     compute_herfindahl
# )
#
# # assume df_ret is a DataFrame of monthly returns for your universe
# weights = {"PCTY": 0.4, "AAPL": 0.6}
#
# # 1) Portfolio returns
# port_ret = compute_portfolio_returns(df_ret, weights)
#
# # 2) Covariance
# cov = compute_covariance_matrix(df_ret)
#
# # 3) Portfolio volatility
# vol = compute_portfolio_volatility(weights, cov)
# print("Portfolio Volatility:", vol)
#
# # 4) Risk contributions
# rc = compute_risk_contributions(weights, cov)
# print("Risk Contributions:\n", rc)
#
# # 5) Concentration (Herfindahl)
# h = compute_herfindahl(weights)
# print("Herfindahl Index:", h)


# In[ ]:


from typing import Any
import json

@log_errors("high")
def compute_portfolio_variance_breakdown(
    weights: Dict[str, float],
    idio_var_dict: Dict[str, float],
    weighted_factor_var: pd.DataFrame,
    vol_m: float
) -> Dict[str, Any]:
    """
    Returns a structured variance decomposition:
      - total variance
      - idiosyncratic variance + %
      - factor variance + %
      - per-factor variance + %
    """
    w = pd.Series(weights)
    w2 = w.pow(2)

    # Idiosyncratic variance (sum of w_i² * σ²_idio_i)
    idio_var_series = pd.Series(idio_var_dict).reindex(w.index).fillna(0.0)
    idio_var = float((w2 * idio_var_series).sum())

    # Factor variance (sum of weighted factor variance matrix)
    factor_var_matrix = (
        weighted_factor_var
        .drop(columns=["industry", "subindustry"], errors="ignore")  # REMOVE
        .fillna(0.0)
    )
    
    per_factor_var = factor_var_matrix.sum(axis=0)
    factor_var = float(per_factor_var.sum())

    # Total portfolio variance
    port_var = factor_var + idio_var

    # % shares
    idio_pct   = idio_var   / port_var if port_var else 0.0
    factor_pct = factor_var / port_var if port_var else 0.0

    # Breakdown of factor variance by factor
    per_factor_var = factor_var_matrix.sum(axis=0)
    per_factor_pct = per_factor_var / port_var

    return {
        "portfolio_variance":      port_var,
        "idiosyncratic_variance":  idio_var,
        "idiosyncratic_pct":       idio_pct,
        "factor_variance":         factor_var,
        "factor_pct":              factor_pct,
        "factor_breakdown_var":    per_factor_var.to_dict(),
        "factor_breakdown_pct":    per_factor_pct.to_dict()
    }

# ============================================================================
# LRU CACHE IMPLEMENTATION FOR PORTFOLIO ANALYSIS
# ============================================================================

def serialize_for_cache(obj):
    """Serialize complex objects for use as cache keys."""
    if obj is None:
        return None
    elif isinstance(obj, dict):
        return json.dumps(obj, sort_keys=True)
    elif isinstance(obj, (list, tuple)):
        return json.dumps(obj, sort_keys=True)
    else:
        return str(obj)

from portfolio_risk_engine.config import PORTFOLIO_RISK_LRU_SIZE

@functools.lru_cache(maxsize=PORTFOLIO_RISK_LRU_SIZE)  # Keep 100 most recent portfolio analyses
def _cached_build_portfolio_view(
    weights_json: str,
    start_date: str,
    end_date: str,
    expected_returns_json: Optional[str] = None,
    stock_factor_proxies_json: Optional[str] = None,
    bond_mask_json: Optional[str] = "[]",
    cache_version: str = "rbeta_v2",
    fmp_ticker_map_json: Optional[str] = None,
    currency_map_json: Optional[str] = None,
    instrument_types_json: Optional[str] = None,
):
    """
    LRU-cached version of build_portfolio_view.
    
    Uses LRU (Least Recently Used) eviction policy - keeps recently accessed
    portfolio analyses in memory while automatically evicting old ones.
    
    Performance Impact:
    - First call: ~2-3 seconds (normal computation)
    - Recent calls: ~10ms (LRU cache retrieval)
    - Memory bounded: Max 100 analyses (~50MB)
    - Automatic cleanup: Least recently used analyses evicted
    """
    # NOTE: bond_mask_json and cache_version are part of the cache key only.
    # Build minimal asset_classes mapping from bond mask for computation
    weights = json.loads(weights_json)
    expected_returns = json.loads(expected_returns_json) if expected_returns_json else None
    stock_factor_proxies = json.loads(stock_factor_proxies_json) if stock_factor_proxies_json else None
    fmp_ticker_map = json.loads(fmp_ticker_map_json) if fmp_ticker_map_json else None
    currency_map = json.loads(currency_map_json) if currency_map_json else None
    instrument_types = json.loads(instrument_types_json) if instrument_types_json else None

    try:
        bond_list = json.loads(bond_mask_json or "[]")
        asset_classes = {t: 'bond' for t in bond_list}
    except Exception:
        asset_classes = None

    # Call the original computation function
    return _build_portfolio_view_computation(
        weights,
        start_date,
        end_date,
        expected_returns,
        stock_factor_proxies,
        asset_classes,
        fmp_ticker_map,
        currency_map,
        instrument_types,
    )

def clear_portfolio_view_cache():
    """Clear the LRU cache for build_portfolio_view."""
    _cached_build_portfolio_view.cache_clear()

def get_portfolio_view_cache_stats():
    """Get LRU cache statistics."""
    cache_info = _cached_build_portfolio_view.cache_info()
    return {
        'cache_type': 'LRU',
        'cache_size': cache_info.currsize,
        'max_size': cache_info.maxsize,
        'hits': cache_info.hits,
        'misses': cache_info.misses,
        'hit_rate': cache_info.hits / (cache_info.hits + cache_info.misses) if (cache_info.hits + cache_info.misses) > 0 else 0
    }

# ============================================================================
# PORTFOLIO ANALYSIS FUNCTIONS
# ============================================================================

def compute_euler_variance_percent(
    *,                       # force keyword args for clarity
    weights: Dict[str, float],
    cov_matrix: pd.DataFrame,
) -> pd.Series:
    """
    Euler (marginal) variance decomposition.

    Returns each asset’s share of **total portfolio variance** as a %
    (values sum exactly to 1.0).

    Parameters
    ----------
    weights     : {ticker: weight}
    cov_matrix  : Σ, index/cols = same tickers
    """
    w = pd.Series(weights, dtype=float).loc[cov_matrix.index]
    # marginal contributions Σ·w
    sigma_w = cov_matrix.values @ w.values
    # component (Euler) contributions w_i · (Σ·w)_i
    contrib = pd.Series(w.values * sigma_w, index=cov_matrix.index)
    return contrib / contrib.sum()          # normalise to 1.0


# In[1]:


# File: portfolio_risk.py

import pandas as pd
import numpy as np
import statsmodels.api as sm
from typing import Dict, List, Optional, Any, Union, Tuple

def _filter_tickers_by_data_availability(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    min_months: int = 12,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], List[str], List[str]]:
    """
    Filter out tickers with insufficient historical data and rebalance remaining weights.
    
    Args:
        weights (Dict[str, float]): Original portfolio weights
        start_date (str): Analysis start date
        end_date (str): Analysis end date  
        min_months (int): Minimum months of data required (default: 12)
        
    Returns:
        tuple: (filtered_weights, excluded_tickers, warnings)
            - filtered_weights: Rebalanced weights for tickers with sufficient data
            - excluded_tickers: List of tickers excluded due to insufficient data
            - warnings: List of warning messages about exclusions
    """
    valid_tickers = {}
    excluded_tickers = []
    warnings = []
    
    # Check data availability for each ticker
    for ticker, weight in weights.items():
        try:
            prices = fetch_monthly_close(
                ticker,
                start_date=start_date,
                end_date=end_date,
                fmp_ticker_map=fmp_ticker_map,
            )
            returns = calc_monthly_returns(prices)
            
            if returns is not None and len(returns) >= min_months:
                valid_tickers[ticker] = weight
            else:
                excluded_tickers.append(ticker)
                months_available = len(returns) if returns is not None else 0
                warnings.append(f"Excluded {ticker}: only {months_available} months of data (need {min_months})")
                
        except Exception as e:
            excluded_tickers.append(ticker)
            warnings.append(f"Excluded {ticker}: data fetch failed ({str(e)[:50]}...)")
    
    # Rebalance weights for remaining tickers
    if valid_tickers:
        total_valid_weight = sum(valid_tickers.values())
        if total_valid_weight > 0:
            # Normalize weights to sum to 1.0
            filtered_weights = {ticker: weight / total_valid_weight 
                             for ticker, weight in valid_tickers.items()}
        else:
            filtered_weights = {}
    else:
        filtered_weights = {}
    
    return filtered_weights, excluded_tickers, warnings

def get_returns_dataframe(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    min_observations: Optional[int] = None,
    instrument_types: Optional[Dict[str, str]] = None,
    fx_attribution_out: Optional[Dict[str, Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """
    Fetch and compute monthly returns for all tickers in the weights dictionary.

    HANDLING NEW/ILLIQUID STOCKS:
    =============================
    Some tickers may not have sufficient historical data for the requested date range.
    This commonly occurs with:
    - Recently IPO'd stocks (e.g., MRP IPO'd Feb 2025, FIG IPO'd Jul 2025)
    - Delisted or restructured securities
    - OTC/illiquid stocks with gaps in data

    When a ticker has no data or insufficient observations (<min_observations monthly
    return observations),
    it is EXCLUDED from the returns DataFrame. This is necessary because:
    1. Covariance matrix estimation requires aligned time series
    2. Statistical reliability requires sufficient observations (typically 12+ months)
    3. Including partial/empty data would corrupt volatility calculations

    The caller (e.g., build_portfolio_view) should re-normalize weights for the
    remaining tickers to ensure they sum to 1.0.

    LOGGING:
    ========
    Excluded tickers are logged via portfolio_logger.warning() so they appear in
    both console output and log files. This ensures visibility into which positions
    are being excluded from risk calculations.

    Args:
        weights (Dict[str, float]): Portfolio weights (tickers as keys).
        start_date (str): Start date in 'YYYY-MM-DD' format.
        end_date (str): End date in 'YYYY-MM-DD' format.
        fmp_ticker_map (Optional[Dict[str, str]]): Mapping of display tickers to FMP tickers
            for international stocks (e.g., {'AT': 'AT.L'}).
        currency_map (Optional[Dict[str, str]]): Mapping of ticker -> ISO currency code
            for non-USD tickers (used to FX-adjust returns).
        min_observations (Optional[int]): Minimum number of monthly return observations
            required for a ticker to be included. If None, uses
            settings.DATA_QUALITY_THRESHOLDS["min_observations_for_expected_returns"].
        instrument_types (Optional[Dict[str, str]]): Optional mapping of ticker ->
            instrument type. When ticker is explicitly tagged as "futures", this
            enables non-USD futures currency auto-detection via IBKR mappings.
        fx_attribution_out (Optional[Dict[str, Dict[str, Any]]]): Optional mutable
            output dict populated for FX-adjusted tickers with keys:
            {"currency", "local_returns", "fx_returns"}.

    Returns:
        pd.DataFrame: Monthly return series for valid tickers only, aligned and cleaned.
            Tickers with no data or insufficient history are excluded.

    Raises:
        ValueError: If ALL tickers fail to fetch data (no valid returns available).
    """
    from portfolio_risk_engine._logging import portfolio_logger

    if min_observations is None:
        try:
            from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS

            min_observations = int(
                DATA_QUALITY_THRESHOLDS.get("min_observations_for_expected_returns", 11)
            )
        except Exception:
            min_observations = 11
    min_observations = max(1, int(min_observations))

    rets = {}
    excluded_no_data = []      # Tickers with no data at all
    excluded_insufficient = []  # Tickers with data but < min_observations

    for t in weights:
        try:
            # Try total return prices first (includes dividends)
            try:
                prices = fetch_monthly_total_return_price(
                    t,
                    start_date=start_date,
                    end_date=end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
            except Exception:
                # Fall back to close prices (price-only, no dividend adjustment)
                prices = fetch_monthly_close(
                    t,
                    start_date=start_date,
                    end_date=end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )

            # Calculate returns from prices
            ticker_returns = calc_monthly_returns(prices)

            # FX-adjust returns for non-USD tickers
            # Priority: 1) explicit currency_map, 2) futures YAML metadata, 3) FMP profile inference
            currency = currency_map.get(t) if currency_map else None
            if not currency and instrument_types:
                instrument_type = str(instrument_types.get(t) or "").strip().lower()
                if instrument_type == "futures":
                    try:
                        from ibkr.compat import get_futures_currency

                        inferred = str(get_futures_currency(t) or "").strip().upper()
                        if inferred and inferred != "USD":
                            currency = inferred
                    except Exception:
                        pass
            if not currency and fmp_ticker_map and t in fmp_ticker_map:
                # Infer currency from FMP profile (same fallback as latest_price())
                try:
                    from portfolio_risk_engine._ticker import fetch_fmp_quote_with_currency, normalize_fmp_price
                    _, fmp_currency = fetch_fmp_quote_with_currency(fmp_ticker_map[t])
                    _, currency = normalize_fmp_price(0, fmp_currency)
                except Exception:
                    pass
            if currency and currency.upper() != "USD":
                try:
                    from portfolio_risk_engine.providers import get_fx_provider

                    fx_provider = get_fx_provider()
                    if fx_provider is None:
                        from fmp.fx import adjust_returns_for_fx

                        if fx_attribution_out is not None:
                            fx_result = adjust_returns_for_fx(
                                ticker_returns,
                                currency,
                                start_date,
                                end_date,
                                decompose=True,
                            )
                            ticker_returns = fx_result["usd_returns"]
                            fx_attribution_out[t] = {
                                "currency": str(currency).strip().upper(),
                                "local_returns": fx_result["local_returns"],
                                "fx_returns": fx_result["fx_returns"],
                            }
                        else:
                            ticker_returns = adjust_returns_for_fx(
                                ticker_returns,
                                currency,
                                start_date,
                                end_date,
                            )
                    elif fx_attribution_out is not None:
                        fx_result = fx_provider.adjust_returns_for_fx(
                            ticker_returns,
                            currency,
                            start_date=start_date,
                            end_date=end_date,
                            decompose=True,
                        )
                        ticker_returns = fx_result["usd_returns"]
                        fx_attribution_out[t] = {
                            "currency": str(currency).strip().upper(),
                            "local_returns": fx_result["local_returns"],
                            "fx_returns": fx_result["fx_returns"],
                        }
                    else:
                        ticker_returns = fx_provider.adjust_returns_for_fx(
                            ticker_returns,
                            currency,
                            start_date=start_date,
                            end_date=end_date,
                        )
                except Exception:
                    pass

            # Check if we have sufficient observations
            if len(ticker_returns) < min_observations:
                excluded_insufficient.append((t, len(ticker_returns)))
            else:
                rets[t] = ticker_returns

        except Exception as e:
            # Ticker has no data available for the requested date range
            # This commonly happens with newly IPO'd stocks
            excluded_no_data.append((t, str(e)[:50]))

    # ─── Log excluded tickers so users are aware of what's missing ───────────────
    if excluded_no_data:
        tickers_str = ", ".join([t for t, _ in excluded_no_data])
        portfolio_logger.warning(
            f"⚠️ EXCLUDED {len(excluded_no_data)} ticker(s) with NO DATA for period "
            f"{start_date} to {end_date}: [{tickers_str}]. "
            f"These may be recently IPO'd stocks or have data gaps."
        )

    if excluded_insufficient:
        details = ", ".join([f"{t}({n}obs)" for t, n in excluded_insufficient])
        portfolio_logger.warning(
            f"⚠️ EXCLUDED {len(excluded_insufficient)} ticker(s) with INSUFFICIENT HISTORY "
            f"(<{min_observations} monthly return observations): [{details}]. "
            f"Minimum {min_observations} observations required for reliable covariance estimation."
        )

    # ─── Validate we have at least some valid tickers ────────────────────────────
    if not rets:
        all_excluded = [t for t, _ in excluded_no_data] + [t for t, _ in excluded_insufficient]
        raise ValueError(
            f"No valid return data available. All {len(weights)} tickers were excluded: {all_excluded}. "
            f"Check that tickers have data for the period {start_date} to {end_date}."
        )

    # ─── Log summary if any tickers were excluded ────────────────────────────────
    total_excluded = len(excluded_no_data) + len(excluded_insufficient)
    if total_excluded > 0:
        portfolio_logger.warning(
            f"📊 Returns DataFrame: {len(rets)}/{len(weights)} tickers valid. "
            f"Excluded {total_excluded} ticker(s). Weights should be re-normalized."
        )

    return pd.DataFrame(rets).dropna()

def compute_target_allocations(
    weights: Dict[str, float],
    expected_returns: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Compute target allocations based on expected returns and equal weight comparison.

    Args:
        weights (Dict[str, float]): Current portfolio weights.
        expected_returns (Optional[Dict[str, float]]): Expected returns for tickers.

    Returns:
        pd.DataFrame: Allocation table with portfolio weight, equal weight, and proportional return targets.
    """
    df = pd.DataFrame({
        "Portfolio Weight": pd.Series(weights),
        "Equal Weight":     pd.Series({t: 1/len(weights) for t in weights})
    })
    if expected_returns:
        total = sum(expected_returns.values())
        df["Prop Target"] = pd.Series({t: expected_returns[t]/total for t in expected_returns})
        df["Prop Diff"]   = df["Portfolio Weight"] - df["Prop Target"]
    df["Eq Diff"] = df["Portfolio Weight"] - df["Equal Weight"]
    return df
    
def _build_bond_injection_mask(
    asset_classes: Optional[Dict[str, str]],
    weights: Dict[str, float]
) -> str:
    """
    Build compact cache key mask for bond tickers getting rate factor analysis.

    Returns a JSON array string of sorted bond tickers or '[]' if none/unknown.
    """
    if not asset_classes:
        return "[]"
    # Read eligible asset classes from centralized config
    try:
        from portfolio_risk_engine.config import RATE_FACTOR_CONFIG
        eligible_classes = set(RATE_FACTOR_CONFIG.get("eligible_asset_classes", ["bond"]))
    except Exception:
        eligible_classes = {"bond"}
    bond_tickers = [t for t in sorted(weights.keys()) if asset_classes.get(t) in eligible_classes]
    return json.dumps(bond_tickers)


def compute_stock_performance_metrics(
    df_ret: pd.DataFrame,
    risk_free_rate: float = 0.04,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compute per-stock performance metrics with portfolio-level conventions.

    Metrics are returned in decimal units (e.g., 0.25 = 25%).
    """
    columns = [
        "Annual Return",
        "Vol A",
        "Sharpe",
        "Sortino",
        "Max Drawdown",
        "Calmar",
        "Downside Dev",
        "Win Rate",
        "Best Month",
        "Worst Month",
    ]

    if df_ret is None or df_ret.empty:
        return pd.DataFrame(columns=columns)

    if start_date is None and isinstance(df_ret.index, pd.DatetimeIndex) and len(df_ret.index) > 0:
        start_date = str(df_ret.index.min().date())
    if end_date is None and isinstance(df_ret.index, pd.DatetimeIndex) and len(df_ret.index) > 0:
        end_date = str(df_ret.index.max().date())

    import logging

    logger = logging.getLogger(__name__)
    risk_free_monthly = risk_free_rate / 12.0
    metrics: Dict[str, Dict[str, float]] = {}

    for ticker in df_ret.columns:
        s = df_ret[ticker].dropna()
        if len(s) < 3:
            logger.warning(
                "Insufficient observations for stock performance metrics: %s (%d months) [%s to %s]",
                ticker,
                len(s),
                start_date,
                end_date,
            )
            metrics[ticker] = {c: 0.0 for c in columns}
            continue

        total_months = len(s)
        years = total_months / 12.0
        total_return = float((1 + s).prod() - 1)
        annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0
        vol_a = float(s.std(ddof=1) * np.sqrt(12))

        if vol_a > 0:
            sharpe = (annual_return - risk_free_rate) / vol_a
        else:
            # Match edge-case convention for constant-return series.
            sharpe = 0.0

        downside_returns = s[s < risk_free_monthly] - risk_free_monthly
        downside_dev = (
            float(np.sqrt((downside_returns**2).mean()) * np.sqrt(12))
            if len(downside_returns) > 0
            else 0.0
        )
        if vol_a <= 0 or downside_dev <= 0:
            sortino = 0.0
        else:
            sortino = (annual_return - risk_free_rate) / downside_dev

        cumulative_returns = (1 + s).cumprod()
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        max_drawdown = float(drawdown.min()) if len(drawdown) > 0 else 0.0
        calmar = abs(annual_return / max_drawdown) if max_drawdown < -0.001 else 0.0

        win_rate = float((s > 0).sum() / len(s)) if len(s) > 0 else 0.0
        best_month = float(s.max()) if len(s) > 0 else 0.0
        worst_month = float(s.min()) if len(s) > 0 else 0.0

        metrics[ticker] = {
            "Annual Return": annual_return,
            "Vol A": vol_a,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "Max Drawdown": max_drawdown,
            "Calmar": calmar,
            "Downside Dev": downside_dev,
            "Win Rate": win_rate,
            "Best Month": best_month,
            "Worst Month": worst_month,
        }

    return (
        pd.DataFrame.from_dict(metrics, orient="index")
        .reindex(columns=columns)
        .replace([np.inf, -np.inf], 0.0)
        .fillna(0.0)
    )


def compute_factor_exposures(
    weights: Dict[str, float],
    df_ret: pd.DataFrame,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]],
    asset_classes: Optional[Dict[str, str]],
    start_date: str,
    end_date: str,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Compute stock-level factor exposures and weighted factor variance.
    """
    _ = df_ret  # Reserved for future in-memory factor alignment optimization

    df_stock_betas = pd.DataFrame(index=weights.keys())
    idio_var_dict: Dict[str, float] = {}

    from portfolio_risk_engine._logging import portfolio_logger

    if stock_factor_proxies:
        missing_proxy_tickers = [t for t in weights if t not in stock_factor_proxies]
        if missing_proxy_tickers:
            portfolio_logger.warning(
                f"Skipping factor analysis for {len(missing_proxy_tickers)} ticker(s) "
                f"with no proxy configuration: [{', '.join(sorted(missing_proxy_tickers))}]. "
                f"Run proxy builder or add entries to stock_factor_proxies."
            )
        for ticker in weights.keys():
            if ticker not in stock_factor_proxies:
                continue
            proxies = stock_factor_proxies[ticker]

            prices = fetch_monthly_close(
                ticker,
                start_date=start_date,
                end_date=end_date,
                fmp_ticker_map=fmp_ticker_map,
            )
            stock_ret = calc_monthly_returns(prices)
            idx = stock_ret.index

            fac_dict: Dict[str, pd.Series] = {}

            mkt_t = proxies.get("market")
            if mkt_t:
                try:
                    mkt_prices = fetch_monthly_total_return_price(
                        mkt_t,
                        start_date=start_date,
                        end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                except Exception:
                    mkt_prices = fetch_monthly_close(
                        mkt_t,
                        start_date=start_date,
                        end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                mkt_ret = calc_monthly_returns(mkt_prices).reindex(idx).dropna()
                fac_dict["market"] = mkt_ret

            mom_t = proxies.get("momentum")
            if mom_t and mkt_t:
                mom_ret = fetch_excess_return(
                    mom_t,
                    mkt_t,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                ).reindex(idx).dropna()
                fac_dict["momentum"] = mom_ret

            val_t = proxies.get("value")
            if val_t and mkt_t:
                val_ret = fetch_excess_return(
                    val_t,
                    mkt_t,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                ).reindex(idx).dropna()
                fac_dict["value"] = val_ret

            for facname in ("industry", "subindustry"):
                proxy = proxies.get(facname)
                if proxy:
                    if isinstance(proxy, list):
                        ser = fetch_peer_median_monthly_returns(
                            proxy,
                            start_date,
                            end_date,
                            fmp_ticker_map=fmp_ticker_map,
                        )
                    else:
                        try:
                            p = fetch_monthly_total_return_price(
                                proxy,
                                start_date=start_date,
                                end_date=end_date,
                                fmp_ticker_map=fmp_ticker_map,
                            )
                        except Exception:
                            p = fetch_monthly_close(
                                proxy,
                                start_date=start_date,
                                end_date=end_date,
                                fmp_ticker_map=fmp_ticker_map,
                            )
                        ser = calc_monthly_returns(p)
                    fac_dict[facname] = ser.reindex(idx).dropna()

            factor_df = pd.DataFrame(fac_dict).dropna(how="any")

            from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS

            min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_factor_betas"]
            if factor_df.empty or len(factor_df) < min_obs:
                continue

            aligned_s = stock_ret.reindex(factor_df.index)

            betas = compute_stock_factor_betas(
                aligned_s,
                {c: factor_df[c] for c in factor_df},
            )
            df_stock_betas.loc[ticker, betas.keys()] = pd.Series(betas)

            X = sm.add_constant(factor_df)
            resid = aligned_s - sm.OLS(aligned_s, X).fit().fittedvalues
            monthly_idio_var = resid.var(ddof=1)
            annual_idio_var = monthly_idio_var * 12
            idio_var_dict[ticker] = float(annual_idio_var)

    interest_rate_vol: Optional[float] = None
    if asset_classes:
        try:
            treas_levels = fetch_monthly_treasury_yield_levels(start_date, end_date)
            dy_df = prepare_rate_factors(treas_levels)
            if not dy_df.empty:
                interest_rate_series = dy_df.sum(axis=1)
                interest_rate_vol = float(interest_rate_series.std(ddof=1) * np.sqrt(12))

                if "interest_rate" not in df_stock_betas.columns:
                    df_stock_betas["interest_rate"] = 0.0

                try:
                    from portfolio_risk_engine.config import RATE_FACTOR_CONFIG

                    eligible_classes = set(
                        RATE_FACTOR_CONFIG.get("eligible_asset_classes", ["bond"])
                    )
                except Exception:
                    eligible_classes = {"bond"}

                for ticker in weights.keys():
                    if asset_classes.get(ticker) not in eligible_classes:
                        df_stock_betas.loc[ticker, "interest_rate"] = 0.0
                        continue

                    try:
                        prices = fetch_monthly_close(
                            ticker,
                            start_date=start_date,
                            end_date=end_date,
                            fmp_ticker_map=fmp_ticker_map,
                        )
                        stock_ret = calc_monthly_returns(prices)
                    except Exception:
                        df_stock_betas.loc[ticker, "interest_rate"] = 0.0
                        continue

                    idx = stock_ret.index
                    rate_fac_dict: Dict[str, pd.Series] = {}
                    for rate_factor_col in dy_df.columns:
                        rate_fac_dict[rate_factor_col] = dy_df[rate_factor_col].reindex(idx).dropna()

                    rate_factor_df = pd.DataFrame(rate_fac_dict).dropna(how="any")

                    from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS

                    min_obs = DATA_QUALITY_THRESHOLDS[
                        "min_observations_for_interest_rate_beta"
                    ]
                    if rate_factor_df.empty or len(rate_factor_df) < min_obs:
                        df_stock_betas.loc[ticker, "interest_rate"] = 0.0
                        continue

                    aligned_s = stock_ret.reindex(rate_factor_df.index)
                    rate_res = compute_multifactor_betas(aligned_s, rate_factor_df, hac_lags=3)
                    rate_betas = rate_res.get("betas", {})
                    interest_rate_beta = float(sum(rate_betas.values())) if rate_betas else 0.0
                    df_stock_betas.loc[ticker, "interest_rate"] = interest_rate_beta
                    try:
                        r2_adj = float(rate_res.get("r2_adj", 0.0))
                        min_r2 = DATA_QUALITY_THRESHOLDS["min_r2_for_rate_factors"]
                        max_beta = DATA_QUALITY_THRESHOLDS["max_reasonable_interest_rate_beta"]

                        if r2_adj < min_r2:
                            from portfolio_risk_engine._logging import log_portfolio_operation

                            log_portfolio_operation(
                                "rate_factor_low_r2",
                                {"ticker": ticker, "r2_adj": r2_adj},
                                execution_time=0,
                            )
                        if abs(interest_rate_beta) > max_beta:
                            from portfolio_risk_engine._logging import log_portfolio_operation

                            log_portfolio_operation(
                                "rate_factor_extreme_beta",
                                {"ticker": ticker, "beta": interest_rate_beta},
                                execution_time=0,
                            )
                        vifs = rate_res.get("vif", {}) or {}
                        if any((v is not None and v > 10) for v in vifs.values()):
                            from portfolio_risk_engine._logging import log_portfolio_operation

                            log_portfolio_operation(
                                "rate_factor_high_vif",
                                {"ticker": ticker, "vif": vifs},
                                execution_time=0,
                            )
                    except Exception:
                        pass
        except Exception as e:
            try:
                from portfolio_risk_engine._logging import log_portfolio_operation

                log_portfolio_operation(
                    "rate_factor_fetch_failed", {"error": str(e)}, execution_time=0
                )
            except Exception:
                pass

    df_factor_vols = pd.DataFrame(index=df_stock_betas.index, columns=df_stock_betas.columns)
    weighted_factor_var = pd.DataFrame(index=df_stock_betas.index, columns=df_stock_betas.columns)

    if stock_factor_proxies:
        for tkr in weights.keys():
            if tkr not in stock_factor_proxies:
                continue
            proxies = stock_factor_proxies[tkr]

            try:
                _p = fetch_monthly_total_return_price(
                    tkr,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
            except Exception:
                _p = fetch_monthly_close(
                    tkr,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
            idx_stock = calc_monthly_returns(_p).index
            fac_ret: Dict[str, pd.Series] = {}

            mkt = proxies.get("market")
            if mkt:
                try:
                    _pm = fetch_monthly_total_return_price(
                        mkt,
                        start_date,
                        end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                except Exception:
                    _pm = fetch_monthly_close(
                        mkt,
                        start_date,
                        end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                fac_ret["market"] = calc_monthly_returns(_pm).reindex(idx_stock).dropna()

            def _excess(etf: str) -> pd.Series:
                return fetch_excess_return(
                    etf,
                    mkt,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                ).reindex(idx_stock).dropna()

            if proxies.get("momentum"):
                if mkt:
                    fac_ret["momentum"] = _excess(proxies["momentum"])
                else:
                    from portfolio_risk_engine._logging import portfolio_logger
                    portfolio_logger.warning(
                        f"⚠️ Skipping momentum factor for {tkr}: no 'market' proxy set "
                        f"(needed to compute excess returns). Add a 'market' proxy "
                        f"(e.g. SPY) to the factor proxies for this ticker."
                    )
            if proxies.get("value"):
                if mkt:
                    fac_ret["value"] = _excess(proxies["value"])
                else:
                    from portfolio_risk_engine._logging import portfolio_logger
                    portfolio_logger.warning(
                        f"⚠️ Skipping value factor for {tkr}: no 'market' proxy set "
                        f"(needed to compute excess returns). Add a 'market' proxy "
                        f"(e.g. SPY) to the factor proxies for this ticker."
                    )

            for fac in ("industry", "subindustry"):
                proxy = proxies.get(fac)
                if proxy:
                    if isinstance(proxy, list):
                        ser = fetch_peer_median_monthly_returns(
                            proxy,
                            start_date,
                            end_date,
                            fmp_ticker_map=fmp_ticker_map,
                        )
                    else:
                        try:
                            _pp = fetch_monthly_total_return_price(
                                proxy,
                                start_date,
                                end_date,
                                fmp_ticker_map=fmp_ticker_map,
                            )
                        except Exception:
                            _pp = fetch_monthly_close(
                                proxy,
                                start_date,
                                end_date,
                                fmp_ticker_map=fmp_ticker_map,
                            )
                        ser = calc_monthly_returns(_pp)
                    fac_ret[fac] = ser.reindex(idx_stock).dropna()

            if not fac_ret:
                continue

            sigmas = pd.Series({f: r.std(ddof=1) * np.sqrt(12) for f, r in fac_ret.items()})
            df_factor_vols.loc[tkr, sigmas.index] = sigmas

        if interest_rate_vol is not None and "interest_rate" in df_factor_vols.columns and asset_classes:
            try:
                from portfolio_risk_engine.config import RATE_FACTOR_CONFIG

                eligible_classes = set(
                    RATE_FACTOR_CONFIG.get("eligible_asset_classes", ["bond"])
                )
            except Exception:
                eligible_classes = {"bond"}
            for tkr in df_factor_vols.index:
                if asset_classes.get(tkr) in eligible_classes:
                    df_factor_vols.loc[tkr, "interest_rate"] = interest_rate_vol
                else:
                    df_factor_vols.loc[tkr, "interest_rate"] = (
                        df_factor_vols.loc[tkr, "interest_rate"]
                        if pd.notna(df_factor_vols.loc[tkr, "interest_rate"])
                        else 0.0
                    )

        df_factor_vols = df_factor_vols.infer_objects(copy=False).fillna(0.0)
        betas_filled = df_stock_betas.infer_objects(copy=False).fillna(0.0)
        weighted_factor_var = calc_weighted_factor_variance(weights, betas_filled, df_factor_vols)

    df_stock_betas_raw = df_stock_betas.copy()
    df_stock_betas_filled = df_stock_betas.infer_objects(copy=False).fillna(0.0)
    w_series = pd.Series(weights, dtype=float).reindex(df_stock_betas_filled.index).fillna(0.0)
    portfolio_factor_betas = df_stock_betas_filled.mul(w_series, axis=0).sum(skipna=True)

    return {
        "df_stock_betas": df_stock_betas_filled,
        "df_stock_betas_raw": df_stock_betas_raw,
        "idio_var_dict": idio_var_dict,
        "df_factor_vols": df_factor_vols,
        "weighted_factor_var": weighted_factor_var,
        "interest_rate_vol": interest_rate_vol,
        "portfolio_factor_betas": portfolio_factor_betas,
    }


def compute_variance_attribution(
    weights: Dict[str, float],
    cov_mat: pd.DataFrame,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]],
    weighted_factor_var: pd.DataFrame,
    idio_var_dict: Dict[str, float],
    vol_m: float,
    df_stock_betas: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Compute Euler, industry, and variance decomposition outputs.
    """
    cov_annual = cov_mat * 12
    euler_var_pct = compute_euler_variance_percent(weights=weights, cov_matrix=cov_annual)

    industry_var_dict: Dict[str, float] = {}
    if stock_factor_proxies:
        for tkr in weights.keys():
            if tkr not in stock_factor_proxies:
                continue
            proxies = stock_factor_proxies[tkr]
            ind = proxies.get("industry")
            if ind:
                v = (
                    weighted_factor_var.loc[tkr, "industry"]
                    if "industry" in weighted_factor_var.columns
                    else 0.0
                )
                industry_var_dict[ind] = industry_var_dict.get(ind, 0.0) + v

    w_series = pd.Series(weights)
    industry_groups: Dict[str, float] = {}
    if stock_factor_proxies:
        for ticker in w_series.index:
            proxy = stock_factor_proxies.get(ticker, {}).get("industry")
            beta = df_stock_betas.get("industry", {}).get(ticker, 0.0)
            weight = w_series[ticker]
            if proxy:
                industry_groups[proxy] = industry_groups.get(proxy, 0.0) + (weight * beta)

    variance_decomposition = compute_portfolio_variance_breakdown(
        weights, idio_var_dict, weighted_factor_var, vol_m
    )
    total_port_var = variance_decomposition["portfolio_variance"]
    industry_pct_dict = {
        k: v / total_port_var if total_port_var else 0.0 for k, v in industry_var_dict.items()
    }

    return {
        "euler_variance_pct": euler_var_pct,
        "industry_variance": {
            "absolute": industry_var_dict,
            "percent_of_portfolio": industry_pct_dict,
            "per_industry_group_beta": industry_groups,
        },
        "variance_decomposition": variance_decomposition,
    }


def compute_asset_vol_summary(
    df_ret: pd.DataFrame,
    weights: Dict[str, float],
    idio_var_dict: Dict[str, float],
    stock_perf_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build per-asset volatility and idiosyncratic summary table.
    """
    _ = df_ret  # Kept for interface stability and parity with stage decomposition.

    w_series = pd.Series(weights)
    vol_a_series = stock_perf_metrics.get("Vol A", pd.Series(dtype=float)).reindex(w_series.index)

    idio_var_a = pd.Series(idio_var_dict).reindex(w_series.index)
    idio_vol_a = idio_var_a.pow(0.5)
    weighted_idio_vol = idio_vol_a * w_series
    weighted_idio_var_model = w_series.pow(2) * idio_var_a

    df_asset = pd.DataFrame(
        {
            "Vol A": vol_a_series,
            "Weighted Vol A": vol_a_series * w_series,
            "Idio Vol A": idio_vol_a,
            "Weighted Idio Vol A": weighted_idio_vol,
            "Weighted Idio Var": weighted_idio_var_model,
        }
    )

    perf_cols = [c for c in stock_perf_metrics.columns if c != "Vol A"]
    if perf_cols:
        perf_df = (
            stock_perf_metrics.reindex(w_series.index)[perf_cols]
            .replace([np.inf, -np.inf], 0.0)
            .fillna(0.0)
        )
        df_asset = df_asset.join(perf_df)

    return df_asset

@log_errors("high")
@log_operation("portfolio_analysis")
@log_timing(3.0)
def build_portfolio_view(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    expected_returns: Optional[Dict[str, float]] = None,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]] = None,
    asset_classes: Optional[Dict[str, str]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build comprehensive portfolio view with LRU caching.
    
    This is the main entry point for portfolio analysis. It uses LRU caching
    to keep recently accessed portfolio analyses in memory for fast retrieval.
    
    Performance:
    - First call: ~2-3 seconds (full computation)
    - Recent calls: ~10ms (LRU cache hit)
    - Memory: Bounded to 100 most recent analyses

    Notes:
    - asset_classes enables rate factor injection for holdings classified as
      'bond' or 'real_estate' (REITs). Cash proxies are excluded by
      classification. When None, behaves like the
      pre-integration implementation.
    - All return series prefer total-return pricing; when adjusted data is
      unavailable, close-only series are used as a fallback.
    - currency_map enables FX-adjusted returns for non-USD holdings.
    - instrument_types allows explicit futures tagging for safe non-USD futures
      currency inference (avoids ticker collisions with equities).
    """
    # Serialize parameters for LRU cache
    weights_json = serialize_for_cache(weights)
    expected_returns_json = serialize_for_cache(expected_returns)
    stock_factor_proxies_json = serialize_for_cache(stock_factor_proxies)
    fmp_ticker_map_json = serialize_for_cache(fmp_ticker_map)
    currency_map_json = serialize_for_cache(currency_map)
    instrument_types_json = serialize_for_cache(instrument_types)

    # Rate beta cache mask and version
    bond_mask_json = _build_bond_injection_mask(asset_classes, weights)
    cache_version = "rbeta_v2"

    # Return cached computation keyed by bond mask and version
    return _cached_build_portfolio_view(
        weights_json, start_date, end_date, expected_returns_json, stock_factor_proxies_json,
        bond_mask_json, cache_version, fmp_ticker_map_json, currency_map_json, instrument_types_json
    )

@log_errors("high")
def _build_portfolio_view_computation(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    expected_returns: Optional[Dict[str, float]] = None,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]] = None,
    asset_classes: Optional[Dict[str, str]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a complete portfolio risk profile."""
    # Stage 0: Portfolio return setup
    fx_attribution: Dict[str, Dict[str, Any]] = {}
    df_ret = get_returns_dataframe(
        weights,
        start_date,
        end_date,
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
        instrument_types=instrument_types,
        fx_attribution_out=fx_attribution,
    )
    fx_attribution = {ticker: value for ticker, value in fx_attribution.items() if ticker in df_ret.columns}

    valid_tickers = set(df_ret.columns)
    excluded_tickers = [t for t in weights if t not in valid_tickers]

    if excluded_tickers:
        from portfolio_risk_engine._logging import portfolio_logger

        # Filter to valid tickers only
        valid_weights = {t: w for t, w in weights.items() if t in valid_tickers}
        total_valid_weight = sum(valid_weights.values())

        if total_valid_weight > 0:
            # Re-normalize so weights sum to 1.0
            weights = {t: w / total_valid_weight for t, w in valid_weights.items()}

            portfolio_logger.warning(
                f"📊 WEIGHTS RE-NORMALIZED: Excluded {len(excluded_tickers)} ticker(s) "
                f"[{', '.join(excluded_tickers)}]. "
                f"Remaining {len(weights)} positions re-normalized from {total_valid_weight:.1%} to 100%."
            )
        else:
            raise ValueError(
                f"Cannot compute portfolio view: all tickers excluded. "
                f"Excluded: {excluded_tickers}"
            )

    df_alloc = compute_target_allocations(weights, expected_returns)
    port_ret = compute_portfolio_returns(df_ret, weights)
    cov_mat = compute_covariance_matrix(df_ret)
    corr_mat = compute_correlation_matrix(df_ret)
    vol_m = compute_portfolio_volatility(weights, cov_mat)
    vol_a = vol_m * np.sqrt(12)
    rc = compute_risk_contributions(weights, cov_mat)
    hhi = compute_herfindahl(weights)

    # Stage 1-2a: Factor analysis
    factor_result = compute_factor_exposures(
        weights=weights,
        df_ret=df_ret,
        stock_factor_proxies=stock_factor_proxies,
        asset_classes=asset_classes,
        start_date=start_date,
        end_date=end_date,
        fmp_ticker_map=fmp_ticker_map,
    )

    # Stage 2b-3: Variance attribution
    var_result = compute_variance_attribution(
        weights=weights,
        cov_mat=cov_mat,
        stock_factor_proxies=stock_factor_proxies,
        weighted_factor_var=factor_result["weighted_factor_var"],
        idio_var_dict=factor_result["idio_var_dict"],
        vol_m=vol_m,
        df_stock_betas=factor_result["df_stock_betas_raw"],
    )

    # Stage 4: Per-stock performance + per-asset summary
    stock_perf = compute_stock_performance_metrics(
        df_ret,
        risk_free_rate=0.04,
        start_date=start_date,
        end_date=end_date,
    )
    df_asset = compute_asset_vol_summary(
        df_ret=df_ret,
        weights=weights,
        idio_var_dict=factor_result["idio_var_dict"],
        stock_perf_metrics=stock_perf,
    )

    return {
        "allocations": df_alloc,
        "covariance_matrix": cov_mat,
        "correlation_matrix": corr_mat,
        "volatility_monthly": vol_m,
        "volatility_annual": vol_a,
        "risk_contributions": rc,
        "herfindahl": hhi,
        "df_stock_betas": factor_result["df_stock_betas"],
        "portfolio_factor_betas": factor_result["portfolio_factor_betas"],
        "factor_vols": factor_result["df_factor_vols"],
        "weighted_factor_var": factor_result["weighted_factor_var"],
        "euler_variance_pct": var_result["euler_variance_pct"],
        "asset_vol_summary": df_asset,
        "portfolio_returns": port_ret,
        "variance_decomposition": var_result["variance_decomposition"],
        "industry_variance": var_result["industry_variance"],
        "fx_attribution": fx_attribution,
    }


# In[ ]:


# ── run_portfolio_risk.py ────────────────────────────────────────────

def _get_risk_free_rate(
    risk_free_rate: Optional[float],
    start_date: str,
    end_date: str,
) -> float:
    """Return annual risk-free rate in decimal units."""
    if risk_free_rate is not None:
        return float(risk_free_rate)

    try:
        from portfolio_risk_engine.data_loader import fetch_monthly_treasury_rates

        treasury_rates = fetch_monthly_treasury_rates("month3", start_date, end_date)
        return float(treasury_rates.mean() / 100.0)
    except Exception as e:
        print(f"⚠️  Treasury rate fetch failed: {type(e).__name__}: {e}")
        print("   Using 4% default risk-free rate")
        return 0.04

def calculate_portfolio_performance_metrics(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = None,
    total_value: Optional[float] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Calculate comprehensive portfolio performance metrics including risk-adjusted returns
    and (optionally) portfolio dividend metrics.
    
    Args:
        weights (Dict[str, float]): Portfolio weights by ticker
        start_date (str): Analysis start date (YYYY-MM-DD)
        end_date (str): Analysis end date (YYYY-MM-DD) 
        benchmark_ticker (str): Benchmark ticker for comparison (default: SPY)
        risk_free_rate (float): Risk-free rate (annual). If None, uses 3-month Treasury yield from FMP
        total_value (float, optional): Total portfolio value; when provided, enables estimated
            annual dividends and top contributor calculations in dividend metrics
        currency_map (Optional[Dict[str, str]]): Mapping of ticker -> ISO currency code
            for non-USD tickers (used to FX-adjust returns).
        
    Returns:
        Dict[str, Any]: Performance metrics including:
            - total_return: Cumulative portfolio return
            - annualized_return: CAGR of the portfolio
            - volatility: Annual volatility
            - sharpe_ratio: Risk-adjusted return vs risk-free rate
            - sortino_ratio: Downside risk-adjusted return
            - information_ratio: Tracking error-adjusted excess return vs benchmark
            - alpha: Excess return vs benchmark (CAPM alpha)
            - beta: Portfolio beta vs benchmark
            - maximum_drawdown: Worst peak-to-trough loss
            - calmar_ratio: Return / max drawdown
            - benchmark_comparison: Side-by-side metrics vs benchmark
            - monthly_performance: Month-by-month returns for analysis
            - dividend_metrics: Portfolio dividend yield analysis with fields:
                • portfolio_dividend_yield (percent)
                • estimated_annual_dividends (dollars; included when total_value provided)
                • individual_yields (per‑ticker percent)
                • dividend_contributions (yield/weight/contribution_pct)
                • data_quality (coverage_by_count, coverage_by_weight, positions_with_dividends, total_positions, failed_tickers)
            - excluded_tickers: List of tickers excluded due to insufficient data (if any)
            - warnings: List of warnings about data quality issues (if any)
    """
    
    # Use a window-aware minimum return-observation gate:
    # a full 12-month calendar window has 11 monthly return observations.
    from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
    default_min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_expected_returns"]
    min_capm_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"]
    try:
        requested_month_points = len(pd.date_range(start=start_date, end=end_date, freq="ME"))
    except Exception:
        requested_month_points = 0
    requested_return_observations = max(1, requested_month_points - 1)
    min_obs = min(default_min_obs, requested_return_observations)

    # Pre-filter tickers with insufficient data and rebalance weights
    filtered_weights, excluded_tickers, warnings = _filter_tickers_by_data_availability(
        weights, start_date, end_date, min_months=min_obs, fmp_ticker_map=fmp_ticker_map
    )
    
    # If no tickers remain after filtering, return error
    if not filtered_weights:
        return {
            "error": "Insufficient data for performance calculation - all tickers excluded",
            "excluded_tickers": excluded_tickers,
            "warnings": warnings
        }
    
    # Get portfolio returns using filtered weights
    df_ret = get_returns_dataframe(
        filtered_weights,
        start_date,
        end_date,
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
        min_observations=min_obs,
    )
    portfolio_returns = compute_portfolio_returns(df_ret, filtered_weights)
    
    # Final safety check (should not trigger after filtering, but just in case)
    if portfolio_returns.empty or len(portfolio_returns) < min_obs:
        return {
            "error": "Insufficient data for performance calculation after filtering",
            "months_available": len(portfolio_returns),
            "excluded_tickers": excluded_tickers,
            "warnings": warnings
        }
    
    # Get benchmark returns
    try:
        benchmark_prices = fetch_monthly_close(
            benchmark_ticker,
            start_date,
            end_date,
            fmp_ticker_map=fmp_ticker_map,
        )
        benchmark_returns = calc_monthly_returns(benchmark_prices)
        
        # Align portfolio and benchmark returns
        aligned_data = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()
        
        if aligned_data.empty:
            return {"error": f"No overlapping data between portfolio and {benchmark_ticker}"}
            
        port_ret = aligned_data['portfolio']
        bench_ret = aligned_data['benchmark']
        
    except Exception as e:
        return {"error": f"Could not fetch benchmark data for {benchmark_ticker}: {str(e)}"}
    
    risk_free_rate = _get_risk_free_rate(risk_free_rate, start_date, end_date)
    
    from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics
    performance_metrics = compute_performance_metrics(
        portfolio_returns=port_ret,
        benchmark_returns=bench_ret,
        risk_free_rate=risk_free_rate,
        benchmark_ticker=benchmark_ticker,
        start_date=start_date,
        end_date=end_date,
        min_capm_observations=min_capm_obs,
    )
    combined_warnings = list(performance_metrics.get("warnings", []))
    
    # Add data quality information if any tickers were excluded
    if excluded_tickers:
        performance_metrics["excluded_tickers"] = excluded_tickers
        combined_warnings.extend(warnings)
        performance_metrics["analysis_notes"] = f"Analysis completed with {len(excluded_tickers)} ticker(s) excluded due to insufficient data"
    if combined_warnings:
        performance_metrics["warnings"] = combined_warnings
    
    # Dividend metrics integration (current-yield method)
    try:
        dividend_metrics = calculate_portfolio_dividend_yield(
            filtered_weights,
            total_value,
            fmp_ticker_map=fmp_ticker_map,
        )
        performance_metrics["dividend_metrics"] = dividend_metrics
    except Exception as e:
        performance_metrics["dividend_metrics"] = {
            "error": f"Dividend calculation failed: {str(e)}",
            "portfolio_dividend_yield": 0.0,
            "data_quality": {
                "coverage_by_weight": 0.0,
                "coverage_by_count": 0.0,
                "positions_with_dividends": 0,
                "total_positions": len(filtered_weights),
                "failed_tickers": list(filtered_weights.keys()),
            },
        }

    return performance_metrics


def calculate_portfolio_dividend_yield(
    weights: Dict[str, float],
    portfolio_value: Optional[float] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Calculate comprehensive portfolio dividend analysis including weighted yield and coverage metrics.

    This function computes portfolio-level dividend metrics by combining individual stock
    dividend yields with portfolio weights, providing both aggregate yield calculations
    and detailed contribution analysis for income-focused portfolio management.

    Methodology:
    1. Fetch individual dividend yields for each position using frequency-based TTM
    2. Calculate weighted portfolio yield based on position sizes
    3. Compute individual contributions to total dividend income
    4. Analyze data quality and coverage metrics
    5. Rank top dividend contributors by dollar contribution

    Args:
        weights (Dict[str, float]): Portfolio weights by ticker symbol
            - Positive values = long positions
            - Negative values = short positions (e.g., cash proxy)
            - Sum should typically equal ~1.0 for fully invested portfolio
        portfolio_value (Optional[float]): Total portfolio value in dollars
            - Used to calculate estimated annual dividend income
            - If provided, enables top contributor ranking by dollar amounts

    Returns:
        Dict[str, Any]: Comprehensive dividend analysis containing:
            - portfolio_dividend_yield (float): Weighted portfolio yield percentage
            - individual_yields (Dict[str, float]): Per-ticker yield percentages  
            - dividend_contributions (Dict[str, Dict]): Detailed contribution analysis
                - yield: Individual stock yield
                - weight: Portfolio weight percentage
                - contribution_pct: Percentage of total dividend income
            - data_quality (Dict): Coverage and quality metrics
                - coverage_by_count: Percentage of positions with dividends
                - coverage_by_weight: Percentage of portfolio value with dividends
                - positions_with_dividends: Count of dividend-paying positions
                - total_positions: Total position count
                - failed_tickers: List of positions with data errors
            - estimated_annual_dividends (float): Total annual dividend income estimate
            - top_dividend_contributors (List[Dict]): Top 5 contributors by dollar amount

    Example:
        >>> weights = {"STWD": 0.2, "DSU": 0.3, "BXMT": 0.1, "NVDA": 0.4}
        >>> result = calculate_portfolio_dividend_yield(weights, 100000)
        >>> print(f"Portfolio yield: {result['portfolio_dividend_yield']:.2f}%")
        >>> print(f"Annual income: ${result['estimated_annual_dividends']:,.0f}")
        Portfolio yield: 6.45%
        Annual income: $6,450

    Note:
        Uses frequency-based TTM methodology for accurate yield calculations
        that closely match financial data provider quotes.
    """
    if not weights:
        return {
            "portfolio_dividend_yield": 0.0,
            "individual_yields": {},
            "dividend_contributions": {},
            "data_quality": {
                "coverage_by_count": 0.0,
                "coverage_by_weight": 0.0,
                "positions_with_dividends": 0,
                "total_positions": 0,
                "failed_tickers": [],
            },
        }

    individual_yields: Dict[str, float] = {}
    failed_tickers: List[str] = []

    for t in weights.keys():
        try:
            individual_yields[t] = fetch_current_dividend_yield(
                t,
                fmp_ticker_map=fmp_ticker_map,
            )
        except Exception:
            individual_yields[t] = 0.0
            failed_tickers.append(t)

    # Weighted portfolio yield (weights as fractions)
    portfolio_yield = 0.0
    total_weight_sum = sum(weights.values()) if weights else 0.0
    for t, w in weights.items():
        y = individual_yields.get(t, 0.0)
        portfolio_yield += (y * w)

    positions_with_div = sum(1 for y in individual_yields.values() if y > 0)
    coverage_by_count = (positions_with_div / len(weights)) if weights else 0.0
    weight_with_div = sum(w for t, w in weights.items() if individual_yields.get(t, 0.0) > 0)
    coverage_by_weight = (weight_with_div / total_weight_sum) if total_weight_sum else 0.0

    dividend_contributions: Dict[str, Dict[str, float]] = {}
    for t, w in weights.items():
        y = individual_yields.get(t, 0.0)
        contrib_pct = (y * w / portfolio_yield * 100.0) if portfolio_yield > 0 else 0.0
        dividend_contributions[t] = {
            "yield": round(y, 4),
            "weight": round(w * 100.0, 4),
            "contribution_pct": round(contrib_pct, 1),
        }

    result: Dict[str, Any] = {
        "portfolio_dividend_yield": round(portfolio_yield, 4),
        "individual_yields": {k: round(v, 4) for k, v in individual_yields.items()},
        "dividend_contributions": dividend_contributions,
        "data_quality": {
            "coverage_by_count": round(coverage_by_count, 3),
            "coverage_by_weight": round(coverage_by_weight, 3),
            "positions_with_dividends": positions_with_div,
            "total_positions": len(weights),
            "failed_tickers": failed_tickers,
        },
    }

    if portfolio_value and portfolio_value > 0:
        est_annual = portfolio_value * (portfolio_yield / 100.0)
        result["estimated_annual_dividends"] = round(est_annual, 2)
        # Top contributors by dollar
        top = []
        for t, d in dividend_contributions.items():
            if d["yield"] > 0:
                dollars = est_annual * (d["contribution_pct"] / 100.0)
                top.append({
                    "ticker": t,
                    "yield": d["yield"],
                    "annual_dividends": round(dollars, 2),
                    "contribution_pct": d["contribution_pct"],
                })
        top.sort(key=lambda x: x["annual_dividends"], reverse=True)
        result["top_dividend_contributors"] = top[:5]

    return result
