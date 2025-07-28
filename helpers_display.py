#!/usr/bin/env python
# coding: utf-8

# In[3]:


import pandas as pd   

# Import logging decorators for display operations
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


# In[4]:


# ─── File: helpers_display.py ──────────────────────────────────────────

EXCLUDE_FACTORS = {"industry"}          # extend if you need to hide more later

@log_error_handling("low")
@log_portfolio_operation_decorator("display_drop_factors")
@log_performance(0.1)
def _drop_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove presentation-only factor rows (case / whitespace agnostic).
    """
    # LOGGING: Add display filtering logging with excluded factor count and names
    if df.empty:
        return df
    idx_mask = (
        df.index.to_series()
          .str.strip()
          .str.lower()
          .isin({f.lower() for f in EXCLUDE_FACTORS})
    )
    return df.loc[~idx_mask]


# In[5]:


# ─── File: helpers_display.py ──────────────────────────────────────────

@log_error_handling("low")
@log_portfolio_operation_decorator("display_print_single_portfolio")
@log_performance(0.2)
def _print_single_portfolio(risk_df, beta_df, title: str = "What-if") -> None:
    """
    Pretty-print risk-limit and factor-beta tables for a *single* portfolio
    (new weights or what-if scenario).

    Parameters
    ----------
    risk_df : pd.DataFrame
        Output from `evaluate_portfolio_risk_limits` (or risk_new in run_what_if)
        with columns ["Metric", "Actual", "Limit", "Pass"].
    beta_df : pd.DataFrame
        Output from `evaluate_portfolio_beta_limits` with columns
        ["portfolio_beta", "max_allowed_beta", "pass", "buffer"] and the
        factor name as index.
    title : str, default "What-if"
        Heading prefix used in the console output.

    Notes
    -----
    • Percentages (`Actual`, `Limit`) are rendered with **one-decimal** precision.
    • Betas, max-betas, and buffer columns are rendered to **four** decimals.
    • Pass/fail booleans are mapped to the strings ``PASS`` / ``FAIL``.
    • Prints directly to stdout; returns None.
    """
    # LOGGING: Add display rendering timing
    # LOGGING: Add data formatting logging
    # LOGGING: Add output validation logging
    pct = lambda x: f"{x:.1%}"                # 1-decimal percentage

    print(f"\n📐  {title} Risk Checks\n")
    print(
        risk_df.to_string(
            index=False,
            formatters={"Actual": pct, "Limit": pct}
        )
    )

    print(f"\n📊  {title} Factor Betas\n")
    beta_df = _drop_factors(beta_df)
    print(
        beta_df.to_string(
            formatters={
                "portfolio_beta":   "{:.4f}".format,
                "max_allowed_beta": "{:.4f}".format,
                "buffer":           "{:.4f}".format,
                "pass":             lambda x: "PASS" if x else "FAIL",
            }
        )
    )


# In[6]:


# ─── File: helpers_display.py ──────────────────────────────────────────

import pandas as pd

@log_error_handling("low")
@log_portfolio_operation_decorator("display_format_percentage")
@log_performance(0.05)
def _fmt_pct(x: float) -> str:
    return f"{x:.1%}"

# ────────────────────────────────────────────────────────────────────
@log_error_handling("medium")
@log_portfolio_operation_decorator("display_compare_risk_tables")
@log_performance(0.3)
def compare_risk_tables(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Side-by-side diff for the risk-limit checker."""
    left  = old.rename(columns={"Actual": "Old",  "Pass": "Old Pass"})
    right = new.rename(columns={"Actual": "New",  "Pass": "New Pass"})
    out   = (
        left.merge(right, on=["Metric", "Limit"], how="outer", sort=False)
            .assign(Δ=lambda d: d["New"] - d["Old"])
            .loc[:, ["Metric", "Old", "New", "Δ", "Limit", "Old Pass", "New Pass"]]
    )
    return out

# ────────────────────────────────────────────────────────────────────
@log_error_handling("medium")
@log_portfolio_operation_decorator("display_compare_beta_tables")
@log_performance(0.3)
def compare_beta_tables(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """
    Diff for the factor-beta checker.
      • Accepts either camel- or snake-case column names.
      • Fills missing Max-Beta / Pass columns with sensible defaults.
      • Index must be Factor for both inputs.
    """
    def _clean(df: pd.DataFrame, tag: str) -> pd.DataFrame:
        colmap = {
            "portfolio_beta": "Beta",
            "max_allowed_beta": "Max Beta",
            "max_beta": "Max Beta",
            "pass": "Pass",
        }
        df = df.rename(columns=colmap)
        if "Max Beta" not in df.columns:
            df["Max Beta"] = 0.0
        if "Pass" not in df.columns:
            df["Pass"] = False
        df = df.rename(columns={"Beta": tag, "Pass": f"{tag} Pass"})
        return df[[tag, "Max Beta", f"{tag} Pass"]]

    left  = _clean(old.copy(), "Old")
    right = _clean(new.copy(), "New")

    merged = left.merge(
        right,
        left_index=True,
        right_index=True,
        how="outer",
        sort=False
    )

    # unify the duplicated Max Beta columns
    merged["Max Beta"] = merged["Max Beta_x"].combine_first(merged["Max Beta_y"])
    merged = merged.drop(columns=["Max Beta_x", "Max Beta_y"])

    out = (
        merged
        .assign(Δ=lambda d: d["New"] - d["Old"])
        .loc[:, ["Old", "New", "Δ", "Max Beta", "Old Pass", "New Pass"]]
    )
    return out


# In[ ]:


# ─── File: helpers_display.py ──────────────────────────────────────────

from typing import Dict, Union

@log_error_handling("low")
@log_portfolio_operation_decorator("display_format_stock_metrics")
@log_performance(0.1)
def format_stock_metrics(metrics_dict: Dict[str, Union[float, int]], title: str) -> None:
    """
    Format stock analysis metrics dictionary into readable output.
    
    Args:
        metrics_dict: Dictionary of metric names to values
        title: Title for the metrics section
    """
    print(f"=== {title} ===")
    
    # Common formatting mappings
    formatters = {
        'monthly_vol': lambda x: f"Monthly Volatility:      {x:.2%}",
        'annual_vol': lambda x: f"Annual Volatility:       {x:.2%}",
        'beta': lambda x: f"Beta:                   {x:.3f}",
        'alpha': lambda x: f"Alpha (Monthly):        {x:.4f}",
        'r_squared': lambda x: f"R-Squared:              {x:.3f}",
        'idio_vol_m': lambda x: f"Idiosyncratic Vol:      {x:.2%}",
        'tracking_error': lambda x: f"Tracking Error:         {x:.2%}",
        'information_ratio': lambda x: f"Information Ratio:      {x:.3f}",
        'total_vol': lambda x: f"Total Volatility:       {x:.2%}",
        'systematic_vol': lambda x: f"Systematic Vol:         {x:.2%}",
        'market_correlation': lambda x: f"Market Correlation:     {x:.3f}",
    }
    
    # Format each metric
    for key, value in metrics_dict.items():
        if key in formatters:
            print(formatters[key](value))
        else:
            # Default formatting for unknown metrics
            if isinstance(value, float):
                if abs(value) < 0.01:  # Very small numbers, likely rates/ratios
                    print(f"{key.replace('_', ' ').title():<20} {value:.4f}")
                elif abs(value) < 1:   # Numbers < 1, likely percentages
                    print(f"{key.replace('_', ' ').title():<20} {value:.2%}")
                else:                  # Larger numbers, likely ratios/multipliers
                    print(f"{key.replace('_', ' ').title():<20} {value:.3f}")
            else:
                print(f"{key.replace('_', ' ').title():<20} {value}")
    
    print()  # Add blank line after section


