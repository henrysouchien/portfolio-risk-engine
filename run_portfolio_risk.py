#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import pandas as pd
import numpy as np
import yaml
from pprint import pprint
from typing import Optional
import statsmodels.api as sm

from typing import Dict, Callable, Union, Optional, Any, List
from data_loader import fetch_monthly_close
from factor_utils import (
    calc_monthly_returns,
    fetch_excess_return,
    fetch_peer_median_monthly_returns,
    compute_volatility,
    compute_regression_metrics,
    compute_factor_metrics,
    compute_stock_factor_betas,
    calc_factor_vols,
    calc_weighted_factor_variance
)
from portfolio_risk import (
    compute_portfolio_returns,
    compute_covariance_matrix,
    compute_correlation_matrix,
    compute_portfolio_volatility,
    compute_risk_contributions,
    compute_herfindahl,
    compute_portfolio_variance_breakdown,
    get_returns_dataframe,
    compute_target_allocations,
    normalize_weights,
    build_portfolio_view  # if reused, or remove if it's redefined in this file
)

# Import logging decorators for portfolio risk operations
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_api_health,
    log_cache_operations,
    log_critical_alert,
    log_service_health
)


# In[ ]:


# File: run_portfolio_risk.py

from typing import Dict, Callable, Union

# Auto-detect cash positions from database (with YAML fallback)
@log_error_handling("medium")
@log_portfolio_operation_decorator("cash_positions_detection")
@log_performance(1.0)
def get_cash_positions():
    """
    Discover the set of tickers that should be treated as cash proxies.

    Resolution order:
        1) Database: query `cash_mappings` via `DatabaseClient.get_cash_mappings()`
           and use `proxy_by_currency` values.
        2) YAML fallback: load `cash_map.yaml` from the project root and use
           `proxy_by_currency` values.
        3) Hard-coded defaults: a minimal set {"SGOV", "ESTR", "IB01", "CASH", "USD"}.

    Returns:
        set[str]: Unique tickers recognized as cash or cash-equivalent proxies.

    Notes:
        - Exposure filtering: Used to exclude positive cash positions when computing
          risky exposures and leverage, while still including negative cash balances
          (margin debt) as risk.
        - Display labeling: Also used by CLI/report formatting to label tickers via
          `format_ticker_with_label(...)`, so cash-like tickers render appropriately
          (e.g., grouping or special casing in displays).
        - The function is decorated with logging and performance instrumentation
          and will emit health signals when the database is unreachable.
    """
    # LOGGING: Add cash position detection logging with data source and timing
    # LOGGING: Add resource usage monitoring for cache initialization here
    # LOGGING: Add critical alert for database connection failures here
    import time
    start_time = time.time()
    
    try:
        # Try database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            cash_map = db_client.get_cash_mappings()
            
            # Log successful database connection
            response_time = time.time() - start_time
            log_service_health("PostgreSQL", "healthy", response_time, user_id=None)
            
            return set(cash_map.get("proxy_by_currency", {}).values())
    except Exception as e:
        # LOGGING: Add critical alert for database connection failures
        response_time = time.time() - start_time
        log_critical_alert("database_connection_failure", "high", f"Database connection failed for cash positions", "Check database connectivity and credentials", details={"error": str(e), "operation": "get_cash_mappings"})
        log_service_health("PostgreSQL", "down", response_time, {"error": str(e)})
        
        # Fallback to YAML
        print(f"⚠️ Database unavailable ({e}), using cash_map.yaml fallback")
        try:
            with open("cash_map.yaml", "r") as f:
                cash_map = yaml.safe_load(f)
                return set(cash_map.get("proxy_by_currency", {}).values())
        except FileNotFoundError:
            # Fallback to common cash proxies
            print("⚠️ cash_map.yaml not found, using default cash proxies")
            return {"SGOV", "ESTR", "IB01", "CASH", "USD"}

cash_positions = get_cash_positions()

@log_error_handling("high")
@log_portfolio_operation_decorator("portfolio_standardization")
@log_performance(2.0)
def standardize_portfolio_input(
    raw_input: Dict[str, Dict[str, Union[float, int]]],
    price_fetcher: Callable[[str], float],
    *,
    currency_map: Optional[Dict[str, str]] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Union[Dict[str, float], float]]:
    """
    Normalize portfolio input into weights using shares, dollar value, or direct weight.

    Args:
        raw_input (dict): Dict of ticker → {"shares": int}, {"dollars": float}, or {"weight": float}
        price_fetcher (callable): Function to fetch latest price for a given ticker
        currency_map (dict, optional): Mapping of ticker -> ISO currency code (non-USD only)
        fmp_ticker_map (dict, optional): Mapping of display ticker -> FMP ticker

    Returns:
        dict: {
            "weights": Dict[ticker, normalized weight],
            "dollar_exposure": Dict[ticker, dollar amount],
            "total_value": float,
            "net_exposure": float,
            "gross_exposure": float,
            "leverage": float
        }
    """
    # LOGGING: Add portfolio standardization start logging with input size and format
    # LOGGING: Add workflow state logging for portfolio standardization workflow here  
    # LOGGING: Add resource usage monitoring for portfolio processing here



    # LOGGING: Add portfolio processing logging with ticker count and validation
    # LOGGING: Add workflow state logging for portfolio processing completion here
    dollar_exposure = {}
    dollars_entry_tickers = set()  # track tickers using raw "dollars" (not price_fetcher)

    # LOGGING: Add portfolio processing logging with ticker count and validation
    for ticker, entry in raw_input.items():
        if "weight" in entry:
            # Will normalize weights separately
            continue
        elif "dollars" in entry:
            raw_dollars = float(entry["dollars"])
            ccy = currency_map.get(ticker) if currency_map else None
            if ccy and ccy.upper() != "USD":
                from fmp.fx import get_fx_rate
                raw_dollars = raw_dollars * get_fx_rate(ccy)
            dollar_exposure[ticker] = raw_dollars
            dollars_entry_tickers.add(ticker)
        elif "shares" in entry:
            price = price_fetcher(ticker)
            dollar_exposure[ticker] = float(entry["shares"]) * price
        else:
            raise ValueError(f"Invalid input for {ticker}: must provide 'shares', 'dollars', or 'weight'.")

    # Warn only for "dollars" entries — "shares" entries go through price_fetcher
    # which already handles FX via latest_price() FMP profile fallback.
    if not currency_map and fmp_ticker_map and dollars_entry_tickers:
        from utils.logging import portfolio_logger
        for ticker in dollars_entry_tickers:
            fmp_sym = fmp_ticker_map.get(ticker, "")
            if any(fmp_sym.endswith(s) for s in (".L", ".TO", ".PA", ".DE", ".HK")):
                portfolio_logger.warning(
                    f"{ticker} appears foreign (FMP: {fmp_sym}) but no currency_map provided - "
                    "treating dollars entry as USD"
                )

    # If any weights were specified, override dollar_exposure logic
    if all("weight" in entry for entry in raw_input.values()):
        weights = {t: float(v["weight"]) for t, v in raw_input.items()}
        normalized_weights = normalize_weights(weights)

        # Calculate exposure excluding only POSITIVE cash positions
        # Negative cash positions (margin debt) should be included
        risky_weights = {
            t: w for t, w in weights.items() 
            if t not in cash_positions or w < 0  # Include negative cash positions (margin debt)
        }
        net_exposure = sum(risky_weights.values())
        gross_exposure = sum(abs(w) for w in risky_weights.values())

        leverage = gross_exposure / net_exposure if net_exposure != 0 else np.inf
        
        return {
            "weights": normalized_weights,
            "dollar_exposure": None,
            "total_value": None,
            "net_exposure": net_exposure,
            "gross_exposure": gross_exposure,
            "leverage": leverage
        }

    total_value = sum(dollar_exposure.values())
    weights = {t: v / total_value for t, v in dollar_exposure.items()}

    # Calculate exposure excluding only POSITIVE cash positions
    # Negative cash positions (margin debt) should be included
    risky_weights = {
        t: w for t, w in weights.items() 
        if t not in cash_positions or w < 0  # Include negative cash positions (margin debt)
    }
    net_exposure = sum(risky_weights.values())
    gross_exposure = sum(abs(w) for w in risky_weights.values())

    leverage = gross_exposure / net_exposure if net_exposure else np.inf

    return {
        "weights": weights,
        "dollar_exposure": dollar_exposure,
        "total_value": total_value,
        "net_exposure": net_exposure,
        "gross_exposure": gross_exposure,
        "leverage": leverage
    }


# In[ ]:


# File: run_portfolio_risk.py

@log_error_handling("high")
def latest_price(
    ticker: str,
    *,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
    currency: str | None = None,
) -> float:
    """
    Fetches the latest available month-end closing price for a given ticker,
    converted to USD.

    FX conversion follows three paths:
    1. Explicit currency provided → convert using month-end FX rate
    2. Foreign FMP mapping exists (fmp_ticker/fmp_ticker_map) → infer currency
       from FMP profile via fetch_fmp_quote_with_currency(), then convert
    3. No currency info, no foreign mapping → assume domestic USD, return raw price

    Args:
        ticker (str): Ticker symbol of the stock or ETF.
        fmp_ticker (str, optional): FMP-compatible symbol override.
        fmp_ticker_map (dict, optional): Mapping of ticker -> fmp_ticker.
        currency (str, optional): Explicit currency code for FX conversion.

    Returns:
        float: Most recent non-NaN month-end closing price in USD.
    """
    from fmp.fx import get_fx_rate
    from utils.ticker_resolver import (
        select_fmp_symbol,
        fetch_fmp_quote_with_currency,
        normalize_fmp_price,
    )

    prices = fetch_monthly_close(
        ticker,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )
    raw_price = prices.dropna().iloc[-1]

    if currency and currency.upper() == "USD":
        return raw_price

    # No currency info and no foreign ticker mapping — assume domestic (USD).
    # Foreign stocks require fmp_ticker_map (e.g. AT→AT.L) for correct exchange
    # resolution, so absence implies US-listed. Avoids extra FMP profile API call.
    if not currency and not fmp_ticker and not (fmp_ticker_map and ticker in fmp_ticker_map):
        return raw_price

    fmp_symbol = select_fmp_symbol(
        ticker,
        fmp_ticker=fmp_ticker,
        fmp_ticker_map=fmp_ticker_map,
    )
    _, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
    normalized_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)

    effective_currency = currency or base_currency
    if effective_currency and effective_currency.upper() != "USD":
        fx_rate = get_fx_rate(effective_currency)
        if normalized_price is not None:
            normalized_price = normalized_price * fx_rate

    return normalized_price if normalized_price is not None else raw_price


# In[ ]:


# ── run_portfolio_risk.py ────────────────────────────────────────────
import yaml
from pprint import pprint
from typing import Dict, Callable, Optional, Any

# --------------------------------------------------------------------
# 1) Pure-data loader  → returns a dict you can reuse programmatically
# --------------------------------------------------------------------
@log_error_handling("high")
@log_portfolio_operation_decorator("config_loading")
@log_performance(0.5)
def load_portfolio_config(
    filepath: str = "portfolio.yaml",
    price_fetcher: Callable[[str], float] | None = None,
) -> Dict[str, Any]:
    """
    Load the YAML and return a dict with parsed + normalised fields.
    No printing, no side effects.
    """
    from run_portfolio_risk import standardize_portfolio_input, latest_price  # local imports
    from pathlib import Path

    resolved_path = Path(filepath)
    if not resolved_path.is_absolute() and not resolved_path.exists():
        candidate = Path(__file__).resolve().parent / resolved_path
        if candidate.exists():
            resolved_path = candidate

    with open(resolved_path, "r") as f:
        cfg_raw = yaml.safe_load(f)

    # • Keep the original keys for downstream code
    cfg: Dict[str, Any] = dict(cfg_raw)          # shallow copy

    fmp_ticker_map = cfg.get("fmp_ticker_map")
    currency_map = cfg.get("currency_map")
    if price_fetcher is None:
        if fmp_ticker_map:
            price_fetcher = lambda t: latest_price(
                t,
                fmp_ticker_map=fmp_ticker_map,
                currency=currency_map.get(t) if currency_map else None,
            )
        else:
            price_fetcher = lambda t: latest_price(
                t,
                currency=currency_map.get(t) if currency_map else None,
            )
    parsed = standardize_portfolio_input(
        cfg["portfolio_input"],
        price_fetcher,
        currency_map=currency_map,
        fmp_ticker_map=fmp_ticker_map,
    )

    cfg.update(
        weights           = parsed["weights"],
        dollar_exposure   = parsed["dollar_exposure"],
        total_value       = parsed["total_value"],
        net_exposure      = parsed["net_exposure"],
        gross_exposure    = parsed["gross_exposure"],
        leverage          = parsed["leverage"],
    )
    return cfg


# --------------------------------------------------------------------
# 2) Pretty-printer  → consumes the dict returned by loader
# --------------------------------------------------------------------
@log_error_handling("low")
@log_portfolio_operation_decorator("portfolio_config_display")
@log_performance(0.5)
def display_portfolio_config(cfg: Dict[str, Any]) -> None:
    """
    Nicely print the fields produced by load_portfolio_config().
    """
    from settings import PORTFOLIO_DEFAULTS
    from utils.logging import portfolio_logger
    from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
    
    # Get reference data for position labeling
    cash_positions = get_cash_positions()
    industry_map = get_etf_to_industry_map()
    
    weights = cfg["weights"]
    
    # Simple check based on the setting
    normalize_setting = PORTFOLIO_DEFAULTS.get("normalize_weights", True)
    title = "=== PORTFOLIO ALLOCATIONS BEING ANALYZED (Normalized Weights) ===" if normalize_setting else "=== PORTFOLIO ALLOCATIONS BEING ANALYZED (Raw Weights) ==="
    
    print(title)
    
    # Sort by weight (descending) for better readability
    sorted_weights = sorted(weights.items(), key=lambda x: abs(x[1]), reverse=True)
    
    # Calculate adaptive column width based on labeled tickers
    max_ticker_width = 8  # minimum width for backwards compatibility
    for ticker, weight in sorted_weights:
        labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
        max_ticker_width = max(max_ticker_width, len(labeled_ticker))
    
    # Add some padding
    max_ticker_width += 2
    
    total_weight = 0
    for ticker, weight in sorted_weights:
        labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
        print(f"{labeled_ticker:<{max_ticker_width}} {weight:>7.2%}")
        total_weight += weight
    
    separator_width = max_ticker_width + 10  # ticker width + percentage width
    print("─" * separator_width)
    print(f"{'Total':<{max_ticker_width}} {total_weight:>7.2%}")
    print()

    print("=== DOLLAR EXPOSURE BY POSITION ===")
    dollar_exp = cfg["dollar_exposure"]
    if dollar_exp is None:
        print("(Dollar exposure not available for weight-based portfolios)")
        print()
    else:
        # Sort by absolute dollar exposure (descending) for better readability
        sorted_dollar = sorted(dollar_exp.items(), key=lambda x: abs(x[1]), reverse=True)
        
        # Calculate adaptive column width for dollar exposure section
        max_dollar_width = 8  # minimum width
        for ticker, amount in sorted_dollar:
            labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
            max_dollar_width = max(max_dollar_width, len(labeled_ticker))
        max_dollar_width += 2  # padding
        
        total_dollar = 0
        for ticker, amount in sorted_dollar:
            labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
            # Format with appropriate precision based on amount size
            if abs(amount) >= 1000:
                print(f"{labeled_ticker:<{max_dollar_width}} ${amount:>12,.0f}")
            else:
                print(f"{labeled_ticker:<{max_dollar_width}} ${amount:>12,.2f}")
            total_dollar += amount
        
        separator_width_dollar = max_dollar_width + 15  # ticker width + dollar amount width
        print("─" * separator_width_dollar)
        if abs(total_dollar) >= 1000:
            print(f"{'Total':<{max_dollar_width}} ${total_dollar:>12,.0f}")
        else:
            print(f"{'Total':<{max_dollar_width}} ${total_dollar:>12,.2f}")
        print()

    print("=== TOTAL PORTFOLIO VALUE ===")
    total_val = cfg["total_value"]
    if total_val is None:
        print("(Total value not available for weight-based portfolios)")
    else:
        if abs(total_val) >= 1000:
            print(f"${total_val:,.0f}")
        else:
            print(f"${total_val:,.2f}")
    
    print("\n=== NET EXPOSURE (sum of weights) ===")
    print(f"{cfg['net_exposure']:.2f}")
    
    print("\n=== GROSS EXPOSURE (sum of abs(weights)) ===")
    print(f"{cfg['gross_exposure']:.2f}")
    
    print("\n=== LEVERAGE (gross / net) ===")
    print(f"{cfg['leverage']:.2f}x")

    print("\n=== EXPECTED RETURNS ===")
    expected_returns = cfg["expected_returns"]
    # Sort by expected return (descending) for better readability
    sorted_returns = sorted(expected_returns.items(), key=lambda x: x[1], reverse=True)
    
    # Calculate adaptive column width for expected returns section
    max_returns_width = 8  # minimum width
    for ticker, return_val in sorted_returns:
        labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
        max_returns_width = max(max_returns_width, len(labeled_ticker))
    max_returns_width += 2  # padding
    
    for ticker, return_val in sorted_returns:
        labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
        print(f"{labeled_ticker:<{max_returns_width}} {return_val:>7.2%}")

    print("\n=== Stock Factor Proxies ===")
    for ticker, proxies in cfg["stock_factor_proxies"].items():
        labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
        print(f"\n→ {labeled_ticker}")
        # Create a copy to avoid modifying original
        display_proxies = proxies.copy()
        
        # Apply industry label to industry proxy if available
        if 'industry' in display_proxies and display_proxies['industry'] in industry_map:
            industry_etf = display_proxies['industry']
            display_proxies['industry'] = f"{industry_etf} ({industry_map[industry_etf]})"
        
        pprint(display_proxies)


# --------------------------------------------------------------------
# 3) Convenience shim for legacy calls  (optional but zero-cost)
# --------------------------------------------------------------------
def load_and_display_portfolio_config(
    filepath: str = "portfolio.yaml",
    price_fetcher: Callable[[str], float] | None = None,
) -> Dict[str, Any]:
    """
    Drop-in replacement for the old monolithic helper.
    Returns the same dict loader now provides.
    """
    cfg = load_portfolio_config(filepath, price_fetcher)
    display_portfolio_config(cfg)
    return cfg


# In[ ]:


# File: run_portfolio_risk.py

@log_error_handling("low")
@log_portfolio_operation_decorator("portfolio_summary_display")
@log_performance(0.5)
def display_portfolio_summary(summary: dict):
    print("\n=== Target Allocations ===")
    print(summary["allocations"], "\n")

    print("=== Covariance Matrix ===")
    print(summary["covariance_matrix"], "\n")

    print("=== Correlation Matrix ===")
    print(summary["correlation_matrix"], "\n")

    print(f"Monthly Volatility:  {summary['volatility_monthly']:.4%}")
    print(f"Annual Volatility:   {summary['volatility_annual']:.4%}\n")

    print("=== Risk Contributions ===")
    print(summary["risk_contributions"], "\n")

    print("Herfindahl Index:", summary["herfindahl"], "\n")

    print("=== Per-Stock Factor Betas ===")
    print(summary["df_stock_betas"], "\n")

    print("=== Portfolio-Level Factor Betas ===")
    print(summary["portfolio_factor_betas"], "\n")

    print("=== Per-Asset Vol & Var ===")
    print(summary["asset_vol_summary"], "\n")

    print("=== Factor Annual Volatilities (σ_i,f) ===")
    print(summary["factor_vols"].round(4))

    print("\n=== Weighted Factor Variance   w_i² · β_i,f² · σ_i,f² ===")
    print(summary["weighted_factor_var"].round(6), "\n")

    print("=== Portfolio Variance Decomposition ===")
    var_dec = summary["variance_decomposition"]
    print(f"Portfolio Variance:          {var_dec['portfolio_variance']:.4f}")
    print(f"Idiosyncratic Variance:      {var_dec['idiosyncratic_variance']:.4f}  ({var_dec['idiosyncratic_pct']:.0%})")
    print(f"Factor Variance:             {var_dec['factor_variance']:.4f}  ({var_dec['factor_pct']:.0%})\n")

    print("=== Factor Variance (absolute) ===")
    for k, v in var_dec["factor_breakdown_var"].items():
        print(f"{k.title():<10} : {v:.5f}")

    filtered = {
        k: v for k, v in var_dec["factor_breakdown_pct"].items()
        if k not in ("industry", "subindustry")
    }

    print("\n=== Top Stock Variance (Euler %) ===")
    euler = summary["euler_variance_pct"]
    top   = dict(sorted(euler.items(), key=lambda kv: -kv[1])[:10])  # top-10
    for tkr, pct in top.items():
        print(f"{tkr:<10} : {pct:6.1%}")
        
    print("\n=== Factor Variance (% of Portfolio, excluding industry) ===")
    for k, v in filtered.items():
        print(f"{k.title():<10} : {v:.0%}")

    print("\n=== Industry Variance (absolute) ===")
    for k, v in summary["industry_variance"]["absolute"].items():
        print(f"{k:<10} : {v:.6f}")

    print("\n=== Industry Variance (% of Portfolio) ===")
    for k, v in summary["industry_variance"]["percent_of_portfolio"].items():
        print(f"{k:<10} : {v:.1%}")

    print("\n=== Per-Industry Group Betas ===")
    per_group = summary["industry_variance"].get("per_industry_group_beta", {})
    
    if per_group:
        # Get reference data for position labeling
        from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
        cash_positions = get_cash_positions()
        industry_map = get_etf_to_industry_map()
        
        # Calculate adaptive column width based on labeled ETF tickers
        max_etf_width = 12  # minimum width for backwards compatibility
        for k, v in per_group.items():
            labeled_etf = format_ticker_with_label(k, cash_positions, industry_map)
            max_etf_width = max(max_etf_width, len(labeled_etf))
        
        # Add some padding
        max_etf_width += 2
        
        # Display with labels and adaptive width
        for k, v in sorted(per_group.items(), key=lambda kv: -abs(kv[1])):
            labeled_etf = format_ticker_with_label(k, cash_positions, industry_map)
            print(f"{labeled_etf:<{max_etf_width}} : {v:>+7.4f}")
    else:
        print("(No per-industry group betas available)")


# In[ ]:


# File: run_portfolio_risk.py

import pandas as pd
from typing import Dict, Optional

@log_error_handling("high")
@log_portfolio_operation_decorator("beta_limits_evaluation")
@log_performance(1.0)
def evaluate_portfolio_beta_limits(
    portfolio_factor_betas: pd.Series,
    max_betas: Dict[str, float],
    proxy_betas: Optional[Dict[str, float]] = None,
    max_proxy_betas: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Compares each factor's actual portfolio beta to the allowable max beta.
    Also supports proxy-level checks like individual industry ETFs.
    
    If proxy-level data (e.g. per-industry ETF) is available, it skips
    the aggregate 'industry' row to avoid double counting.

    Parameters
    ----------
    portfolio_factor_betas : pd.Series
        e.g. {"market": 0.74, "momentum": 1.1, ...}
    max_betas : dict
        e.g. {"market": 0.80, "momentum": 1.56, ...}
    proxy_betas : dict, optional
        e.g. {"SOXX": 0.218, "KCE": 0.287}
    max_proxy_betas : dict, optional
        e.g. {"SOXX": 0.56, "KCE": 0.49}

    Returns
    -------
    pd.DataFrame
        Rows: factors and proxies. Columns: portfolio_beta, max_allowed_beta, pass, buffer.
    """
    rows = []

    skip_industry = proxy_betas is not None and max_proxy_betas is not None

    # ─── Factor-level checks ─────────────────────────────────
    for factor, max_b in max_betas.items():
        if skip_industry and factor == "industry":
            continue  # skip aggregate industry if per-proxy provided

        actual = portfolio_factor_betas.get(factor, 0.0)
        rows.append({
            "factor": factor,
            "portfolio_beta": actual,
            "max_allowed_beta": max_b,
            "pass": abs(actual) <= max_b,
            "buffer": max_b - abs(actual),
        })

    # ─── Proxy-level checks (e.g. SOXX, XSW) ─────────────────
    if proxy_betas and max_proxy_betas:
        for proxy, actual in proxy_betas.items():
            max_b = max_proxy_betas.get(proxy, float("inf"))
            label = f"industry_proxy::{proxy}"
            rows.append({
                "factor": label,
                "portfolio_beta": actual,
                "max_allowed_beta": max_b,
                "pass": abs(actual) <= max_b,
                "buffer": max_b - abs(actual),
            })

    if not rows:
        df = pd.DataFrame(columns=["portfolio_beta", "max_allowed_beta", "pass", "buffer"])
        df.index.name = "factor"
        return df

    df = pd.DataFrame(rows).set_index("factor")
    return df[["portfolio_beta", "max_allowed_beta", "pass", "buffer"]]


# In[ ]:


# File: run_portfolio_risk.py

from typing import Dict, Any
import pandas as pd

@log_error_handling("high")
@log_portfolio_operation_decorator("risk_limits_evaluation")
@log_performance(1.0)
def evaluate_portfolio_risk_limits(
    summary: Dict[str, Any],
    portfolio_limits: Dict[str, float],
    concentration_limits: Dict[str, float],
    variance_limits: Dict[str, float]
) -> pd.DataFrame:
    """
    Evaluates portfolio risk metrics against configured limits.

    Args:
        summary (dict): Output from build_portfolio_view().
        portfolio_limits (dict): {"max_volatility": float, "max_loss": float}
        concentration_limits (dict): {"max_single_stock_weight": float}
        variance_limits (dict): Keys include "max_factor_contribution", etc.

    Returns:
        pd.DataFrame: One row per check with actual, limit, and pass/fail.
    """
    # LOGGING: Add risk limits evaluation start logging with limit types and values
    results = []

    # LOGGING: Add volatility check logging with actual vs limit values
    # 1. Volatility Check
    actual_vol = summary["volatility_annual"]
    vol_limit = portfolio_limits["max_volatility"]
    results.append({
        "Metric": "Volatility",
        "Actual": actual_vol,
        "Limit": vol_limit,
        "Pass": actual_vol <= vol_limit
    })

    # 2. Concentration Check
    weights = summary["allocations"]["Portfolio Weight"]
    max_weight = weights.abs().max()
    weight_limit = concentration_limits["max_single_stock_weight"]
    results.append({
        "Metric": "Max Weight",
        "Actual": max_weight,
        "Limit": weight_limit,
        "Pass": max_weight <= weight_limit
    })

    # 3. Factor Variance Contribution
    var_decomp = summary["variance_decomposition"]
    factor_pct = var_decomp["factor_pct"]
    factor_limit = variance_limits["max_factor_contribution"]
    results.append({
        "Metric": "Factor Var %",
        "Actual": factor_pct,
        "Limit": factor_limit,
        "Pass": factor_pct <= factor_limit
    })

    # 4. Market Variance Contribution
    market_pct = var_decomp["factor_breakdown_pct"].get("market", 0.0)
    market_limit = variance_limits["max_market_contribution"]
    results.append({
        "Metric": "Market Var %",
        "Actual": market_pct,
        "Limit": market_limit,
        "Pass": market_pct <= market_limit
    })

    # 5. Top Industry Exposure
    industry_pct_dict = summary["industry_variance"].get("percent_of_portfolio", {})
    max_industry_pct = max(industry_pct_dict.values()) if industry_pct_dict else 0.0
    industry_limit = variance_limits["max_industry_contribution"]
    results.append({
        "Metric": "Max Industry Var %",
        "Actual": max_industry_pct,
        "Limit": industry_limit,
        "Pass": max_industry_pct <= industry_limit
    })

    return pd.DataFrame(results)


# In[ ]:


# File: run_portfolio_risk.py

@log_error_handling("low")
@log_portfolio_operation_decorator("performance_metrics_display")
@log_performance(0.5)
def display_portfolio_performance_metrics(performance_metrics: Dict[str, Any]) -> None:
    """
    Display comprehensive portfolio performance metrics in a formatted, professional layout.
    
    Shows complete performance analysis including returns, risk metrics, benchmark analysis,
    and dividend analysis (if available). Designed for CLI output with professional formatting
    suitable for portfolio managers and institutional analysis.
    
    Display Sections:
    - Portfolio Performance Analysis header with period and position count
    - Return Metrics: Total return, annualized return, win rate statistics
    - Risk Metrics: Volatility, maximum drawdown, downside deviation
    - Risk-Adjusted Returns: Sharpe, Sortino, Information, Calmar ratios
    - Benchmark Analysis: Alpha, beta, R-squared vs benchmark (typically SPY)
    - Portfolio vs Benchmark Comparison: Side-by-side performance table
    - Monthly Statistics: Average returns, win/loss ratios, period breakdown
    - Risk-Free Rate: Current Treasury rate used in calculations
    - Dividend Analysis: Portfolio yield, coverage, and top contributors (if available)
    - Performance Summary: Overall assessment and category
    - Key Insights: Bullet-point summary of key findings
    
    Parameters
    ----------
    performance_metrics : Dict[str, Any]
        Complete output from calculate_portfolio_performance_metrics() containing:
        - returns: Return statistics and period analysis
        - risk_metrics: Volatility and drawdown metrics  
        - risk_adjusted_returns: Risk-adjusted performance ratios
        - benchmark_analysis: Benchmark comparison statistics
        - monthly_stats: Period-by-period performance breakdown
        - dividend_metrics: Dividend yield analysis and coverage
        - analysis_period: Time period configuration and metadata
        
    Example Output:
        📊 PORTFOLIO PERFORMANCE ANALYSIS
        ============================================================
        📅 Analysis Period: 2019-01-31 to 2025-06-27
        📊 Total Months: 18 (1.58 years)
        ...
        💰 DIVIDEND ANALYSIS
        ────────────────────────────────────────
        📈 Portfolio Dividend Yield:   6.45%
        💵 Est. Annual Dividends:   $     9,784
        🏆 Top Dividend Contributors:
           1. DSU: 11.16% yield (54.4% of income)
           2. STWD: 9.47% yield (21.5% of income)
    """
    
    # Check for errors
    if "error" in performance_metrics:
        print(f"❌ Error: {performance_metrics['error']}")
        return
    
    # Extract data
    period = performance_metrics["analysis_period"]
    returns = performance_metrics["returns"]
    risk = performance_metrics["risk_metrics"]
    ratios = performance_metrics["risk_adjusted_returns"]
    benchmark = performance_metrics["benchmark_analysis"]
    comparison = performance_metrics["benchmark_comparison"]
    monthly = performance_metrics["monthly_stats"]
    
    # Header
    print("\n" + "="*60)
    print("📊 PORTFOLIO PERFORMANCE ANALYSIS")
    print("="*60)
    
    # Analysis period
    print(f"📅 Analysis Period: {period['start_date']} to {period['end_date']}")
    print(f"📊 Total Months: {period['total_months']} ({period['years']} years)")
    
    # Core performance metrics
    print(f"\n📈 RETURN METRICS")
    print("─" * 40)
    print(f"📊 Total Return:        {returns['total_return']:>8.2f}%")
    print(f"📈 Annualized Return:   {returns['annualized_return']:>8.2f}%")
    print(f"🟢 Best Month:          {returns['best_month']:>8.2f}%")
    print(f"🔴 Worst Month:         {returns['worst_month']:>8.2f}%")
    print(f"🎯 Win Rate:            {returns['win_rate']:>8.1f}%")
    
    # Risk metrics
    print(f"\n⚡ RISK METRICS")
    print("─" * 40)
    print(f"📉 Volatility:          {risk['volatility']:>8.2f}%")
    print(f"📉 Max Drawdown:        {risk['maximum_drawdown']:>8.2f}%")
    print(f"📊 Downside Deviation:  {risk['downside_deviation']:>8.2f}%")
    print(f"📈 Tracking Error:      {risk['tracking_error']:>8.2f}%")
    
    # Risk-adjusted returns
    print(f"\n🎯 RISK-ADJUSTED RETURNS")
    print("─" * 40)
    print(f"⚡ Sharpe Ratio:        {ratios['sharpe_ratio']:>8.3f}")
    print(f"📊 Sortino Ratio:       {ratios['sortino_ratio']:>8.3f}")
    print(f"📈 Information Ratio:   {ratios['information_ratio']:>8.3f}")
    print(f"📉 Calmar Ratio:        {ratios['calmar_ratio']:>8.3f}")
    
    # Benchmark analysis
    print(f"\n🔍 BENCHMARK ANALYSIS ({benchmark['benchmark_ticker']})")
    print("─" * 40)
    alpha = benchmark.get("alpha_annual")
    beta = benchmark.get("beta")
    r_squared = benchmark.get("r_squared")
    alpha_text = f"{alpha:>8.2f}%" if alpha is not None else "     N/A"
    beta_text = f"{beta:>8.3f}" if beta is not None else "     N/A"
    r_squared_text = f"{r_squared:>8.3f}" if r_squared is not None else "     N/A"
    print(f"🎯 Alpha (Annual):      {alpha_text}")
    print(f"📊 Beta:                {beta_text}")
    print(f"📈 R-Squared:           {r_squared_text}")
    print(f"📊 Excess Return:       {benchmark['excess_return']:>8.2f}%")
    
    # Portfolio vs Benchmark comparison
    print(f"\n📊 PORTFOLIO vs {benchmark['benchmark_ticker']} COMPARISON")
    print(f"{'Metric':<21}{'Portfolio':>10}  {'Benchmark':>10}")
    print("─" * 43)
    print(f"{'Total Return':<21}{comparison.get('portfolio_total_return', comparison['portfolio_return']):>9.2f}%  {comparison.get('benchmark_total_return', comparison['benchmark_return']):>9.2f}%")
    print(f"{'Ann. Return':<21}{comparison['portfolio_return']:>9.2f}%  {comparison['benchmark_return']:>9.2f}%")
    print(f"{'Volatility':<21}{comparison['portfolio_volatility']:>9.2f}%  {comparison['benchmark_volatility']:>9.2f}%")
    print(f"{'Sharpe Ratio':<21}{comparison['portfolio_sharpe']:>10.3f}  {comparison['benchmark_sharpe']:>10.3f}")
    
    # Monthly statistics
    print(f"\n📅 MONTHLY STATISTICS")
    print("─" * 40)
    print(f"📊 Avg Monthly Return:  {monthly['average_monthly_return']:>8.2f}%")
    print(f"🟢 Average Win:         {monthly['average_win']:>8.2f}%")
    print(f"🔴 Average Loss:        {monthly['average_loss']:>8.2f}%")
    print(f"⚖️  Win/Loss Ratio:     {monthly['win_loss_ratio']:>8.2f}")
    print(f"📊 Positive Months:     {returns['positive_months']:>8.0f}")
    print(f"📉 Negative Months:     {returns['negative_months']:>8.0f}")
    
    # Risk-free rate
    print(f"\n🏦 RISK-FREE RATE")
    print("─" * 40)
    print(f"📊 3-Month Treasury:    {performance_metrics['risk_free_rate']:>8.2f}%")

    # Dividend analysis (optional)
    dividend_data = performance_metrics.get("dividend_metrics")
    if dividend_data and not isinstance(dividend_data, dict) and hasattr(dividend_data, 'get'):
        # Just in case a different mapping-like type is used
        dividend_data = dict(dividend_data)
    if isinstance(dividend_data, dict) and "error" not in dividend_data:
        print(f"\n💰 DIVIDEND ANALYSIS")
        print("─" * 40)
        port_yield = dividend_data.get("portfolio_dividend_yield", 0.0) or 0.0
        print(f"📈 Portfolio Dividend Yield: {port_yield:>6.2f}%")

        if "estimated_annual_dividends" in dividend_data and dividend_data["estimated_annual_dividends"] is not None:
            try:
                ann_div = float(dividend_data["estimated_annual_dividends"])  # dollars
                print(f"💵 Est. Annual Dividends:   ${ann_div:>10,.0f}")
            except Exception:
                pass

        dq = dividend_data.get("data_quality", {}) or {}
        try:
            cov_w = float(dq.get("coverage_by_weight", 0.0)) * 100.0
        except Exception:
            cov_w = 0.0
        pos_with = dq.get("positions_with_dividends", 0) or 0
        pos_total = dq.get("total_positions", 0) or 0
        print(f"📊 Dividend Coverage:      {cov_w:>6.1f}% ({pos_with}/{pos_total} positions)")

        # Top contributors (up to 3)
        top = dividend_data.get("top_dividend_contributors") or []
        if top:
            print(f"🏆 Top Dividend Contributors:")
            for i, c in enumerate(top[:3], 1):
                tkr = c.get("ticker", "?")
                yld = c.get("yield", 0.0) or 0.0
                contrib = c.get("contribution_pct", 0.0) or 0.0
                print(f"   {i}. {tkr}: {yld:.2f}% yield ({contrib:.1f}% of income)")
    
    # Performance summary
    print(f"\n✅ PERFORMANCE SUMMARY")
    print("─" * 40)
    
    # Determine performance quality
    annual_return = returns['annualized_return']
    sharpe = ratios['sharpe_ratio']
    max_dd = abs(risk['maximum_drawdown'])
    
    if annual_return > 15 and sharpe > 1.0 and max_dd < 20:
        quality = "🟢 EXCELLENT"
        summary = "Strong returns with good risk management"
    elif annual_return > 10 and sharpe > 0.8 and max_dd < 30:
        quality = "🟡 GOOD"
        summary = "Solid performance with acceptable risk"
    elif annual_return > 5 and sharpe > 0.5 and max_dd < 40:
        quality = "🟠 FAIR"
        summary = "Moderate performance with some risk concerns"
    else:
        quality = "🔴 POOR"
        summary = "Underperforming with significant risk issues"
    
    print(f"{quality}: {summary}")
    
    # Key insights
    print(f"\n💡 KEY INSIGHTS")
    print("─" * 40)
    
    # Alpha analysis
    if alpha is None:
        print(f"   • Alpha unavailable (insufficient data for regression vs {benchmark['benchmark_ticker']})")
    elif alpha > 3:
        print(f"   • Strong alpha generation (+{alpha:.1f}% vs {benchmark['benchmark_ticker']})")
    elif alpha > 0:
        print(f"   • Modest alpha generation (+{alpha:.1f}% vs {benchmark['benchmark_ticker']})")
    else:
        print(f"   • Underperforming benchmark ({alpha:+.1f}% vs {benchmark['benchmark_ticker']})")

    # Beta analysis
    if beta is None:
        print("   • Beta unavailable (insufficient data for regression)")
    elif beta > 1.2:
        print(f"   • High market sensitivity (β = {beta:.2f})")
    elif beta > 0.8:
        print(f"   • Moderate market sensitivity (β = {beta:.2f})")
    else:
        print(f"   • Low market sensitivity (β = {beta:.2f})")
    
    # Sharpe analysis
    if ratios['sharpe_ratio'] > 1.0:
        print(f"   • Good risk-adjusted returns (Sharpe = {ratios['sharpe_ratio']:.2f})")
    elif ratios['sharpe_ratio'] > 0.5:
        print(f"   • Acceptable risk-adjusted returns (Sharpe = {ratios['sharpe_ratio']:.2f})")
    else:
        print(f"   • Poor risk-adjusted returns (Sharpe = {ratios['sharpe_ratio']:.2f})")
    
    # Win rate analysis
    if returns['win_rate'] > 60:
        print(f"   • High consistency ({returns['win_rate']:.0f}% win rate)")
    elif returns['win_rate'] > 50:
        print(f"   • Moderate consistency ({returns['win_rate']:.0f}% win rate)")
    else:
        print(f"   • Low consistency ({returns['win_rate']:.0f}% win rate)")
    
    print("="*60)
