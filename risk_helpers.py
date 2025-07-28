#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# === Imports for Risk Helper Functions ===

from data_loader import fetch_monthly_close
from factor_utils import calc_monthly_returns

# Import logging decorators for risk helper functions
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


# In[ ]:


from typing import Dict, Union, List
import pandas as pd

@log_error_handling("high")
def get_worst_monthly_factor_losses(
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    start_date: str,
    end_date: str
) -> Dict[str, float]:
    """
    For each unique factor proxy (ETF or peer group), fetch monthly returns over a historical window,
    and compute the worst single-month return (min).

    Only includes factor types: market, momentum, value, and industry.

    Args:
        stock_factor_proxies (Dict): From portfolio.yaml — maps tickers to their factor proxies.
        start_date (str): Start date for return window (YYYY-MM-DD).
        end_date (str): End date for return window (YYYY-MM-DD).

    Returns:
        Dict[str, float]: {proxy: worst 1-month return}
    """
    # LOGGING: Add risk calculation timing
    # LOGGING: Add mathematical operation logging
    # LOGGING: Add validation step logging
    # LOGGING: Add error context logging
    from data_loader import fetch_monthly_close
    from factor_utils import calc_monthly_returns

    allowed_factors = {"market", "momentum", "value", "industry"}
    unique_proxies = set()

    for proxy_map in stock_factor_proxies.values():
        for k, v in proxy_map.items():
            if k not in allowed_factors:
                continue  # skip subindustry and others
            if isinstance(v, list):
                unique_proxies.update(v)
            else:
                unique_proxies.add(v)

    worst_losses = {}

    for proxy in sorted(unique_proxies):
        try:
            prices = fetch_monthly_close(proxy, start_date, end_date)
            returns = calc_monthly_returns(prices)
            if not returns.empty:
                worst_losses[proxy] = float(returns.min())
        except Exception as e:
            print(f"⚠️ Failed for proxy {proxy}: {e}")

    return worst_losses


# In[ ]:


from typing import Dict, Union, List, Tuple

def aggregate_worst_losses_by_factor_type(
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    worst_losses: Dict[str, float]
) -> Dict[str, Tuple[str, float]]:
    """
    Aggregate the worst 1-month return per factor type by scanning all proxies
    assigned to each factor type across the portfolio and selecting the worst-performing one.

    Args:
        stock_factor_proxies (Dict): Mapping from tickers to their factor proxy assignments.
        worst_losses (Dict): Precomputed worst monthly return per ETF or peer.

    Returns:
        Dict[str, Tuple[str, float]]: {factor_type: (proxy, worst_return)}
    """
    factor_types = ["market", "momentum", "value", "industry"]
    factor_to_proxies: Dict[str, set] = {ftype: set() for ftype in factor_types}

    for proxy_map in stock_factor_proxies.values():
        for ftype in factor_types:
            proxy = proxy_map.get(ftype)
            if isinstance(proxy, list):
                factor_to_proxies[ftype].update(proxy)
            elif proxy:
                factor_to_proxies[ftype].add(proxy)

    factor_worst: Dict[str, Tuple[str, float]] = {}
    for ftype, proxies in factor_to_proxies.items():
        worst_proxy = None
        worst_val = float("inf")
        for proxy in proxies:
            val = worst_losses.get(proxy)
            if val is not None and val < worst_val:
                worst_val = val
                worst_proxy = proxy
        if worst_proxy is not None:
            factor_worst[ftype] = (worst_proxy, worst_val)

    return factor_worst


# In[ ]:


# ─── risk_helpers.py ──────────────────────────────────────────────

from typing import Dict, Tuple, List
import pandas as pd

def compute_max_betas(
    proxies: Dict[str, Dict[str, List[str] | str]],
    start_date: str,
    end_date:   str,
    loss_limit_pct: float,
) -> Dict[str, float]:
    """
    Pure function – NO YAML reads, NO printing.

    Parameters
    ----------
    proxies : dict          # stock_factor_proxies section
    start_date, end_date : str  # analysis window (YYYY-MM-DD)
    loss_limit_pct : float      # e.g. -0.10

    Returns
    -------
    {factor_type: max_beta}
    """
    from risk_helpers import (
        get_worst_monthly_factor_losses,
        aggregate_worst_losses_by_factor_type,
    )

    worst_losses   = get_worst_monthly_factor_losses(proxies, start_date, end_date)
    worst_by_type  = aggregate_worst_losses_by_factor_type(proxies, worst_losses)

    return {
        ftype: float("inf") if worst >= 0 else loss_limit_pct / worst
        for ftype, (_, worst) in worst_by_type.items()
    }


# In[ ]:


# ─── risk_helpers.py ─────────────────────────────────────────────────────────

from typing import Dict, Tuple, List
from datetime import datetime
import yaml
import pandas as pd

@log_error_handling("high")
def calc_max_factor_betas(
    portfolio_yaml: str = "portfolio.yaml",
    risk_yaml: str = "risk_limits.yaml",
    lookback_years: int = None,
    echo: bool = True,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Derive max-allowable portfolio betas for each factor type and industry
    from historical worst 1-month factor proxy returns.

    Parameters
    ----------
    portfolio_yaml : str
        Path to the YAML file containing `stock_factor_proxies`.
    risk_yaml : str
        Path to YAML containing `max_single_factor_loss`.
    lookback_years : int, optional
        Historical window length to scan (ending today).
        If None, uses PORTFOLIO_DEFAULTS['worst_case_lookback_years'].
    echo : bool
        If True, pretty-prints the intermediate tables to stdout.

    Returns
    -------
    Tuple[Dict[str, float], Dict[str, float]]
        - max_betas:         {factor_type: max_beta}
        - max_betas_by_proxy: {industry_proxy: max_beta}
    """
    # 1. --- load configs -----------------------------------------------------
    with open(portfolio_yaml, "r") as f:
        port_cfg = yaml.safe_load(f)
    with open(risk_yaml, "r") as f:
        risk_cfg = yaml.safe_load(f)

    proxies = port_cfg["stock_factor_proxies"]
    loss_limit = risk_cfg["max_single_factor_loss"]  # e.g. -0.10
    
    # Use default from settings if not specified
    if lookback_years is None:
        from settings import PORTFOLIO_DEFAULTS
        lookback_years = PORTFOLIO_DEFAULTS['worst_case_lookback_years']

    # 2. --- date window ------------------------------------------------------
    end_dt = datetime.today()
    start_dt = end_dt - pd.DateOffset(years=lookback_years)
    end_str, start_str = end_dt.strftime("%Y-%m-%d"), start_dt.strftime("%Y-%m-%d")

    # 3. --- worst per-proxy --------------------------------------------------
    worst_per_proxy = get_worst_monthly_factor_losses(
        proxies, start_str, end_str
    )

    # 4. --- worst per factor-type -------------------------------------------
    worst_by_factor = aggregate_worst_losses_by_factor_type(
        proxies, worst_per_proxy
    )

    # 5. --- max beta per factor type ----------------------------------------------------
    max_betas = compute_max_betas(
        proxies, start_str, end_str, loss_limit
    )

    # 6. Compute per-industry-proxy max betas
    industry_proxies = set()
    for proxy_map in proxies.values():
        proxy = proxy_map.get("industry")
        if isinstance(proxy, list):
            industry_proxies.update(proxy)
        elif proxy:
            industry_proxies.add(proxy)

    max_betas_by_proxy = {}
    for proxy in sorted(industry_proxies):
        worst = worst_per_proxy.get(proxy)
        if worst is None or worst >= 0:
            max_betas_by_proxy[proxy] = float("inf")
        else:
            max_betas_by_proxy[proxy] = loss_limit / worst

    # --- pretty print block --------------------------------------------------
    if echo:
        print(f"\n=== Historical Worst-Case Analysis ({lookback_years}-year lookback) ===")
        print(f"Analysis Period: {start_str} to {end_str}")
        
        print("\n=== Worst Monthly Losses per Proxy ===")
        for p, v in sorted(worst_per_proxy.items(), key=lambda kv: kv[1]):
            print(f"{p:<12} : {v:.2%}")

        print("\n=== Worst Monthly Losses per Factor Type ===")
        for ftype, (p, v) in worst_by_factor.items():
            print(f"{ftype:<10} → {p:<12} : {v:.2%}")

        print(f"\n=== Max Allowable Beta per Factor "
              f"(Loss Limit = {loss_limit:.0%}) ===")
        for ftype, beta in max_betas.items():
            print(f"{ftype:<10} → β ≤ {beta:.2f}")

        print("\n=== Max Beta per Industry Proxy ===")
        for p, b in sorted(max_betas_by_proxy.items()):
            print(f"{p:<12} → β ≤ {b:.2f}")

    return max_betas, max_betas_by_proxy

