#!/usr/bin/env python
# coding: utf-8

# In[3]:


import pandas as pd   


# In[4]:


# ─── File: helpers_display.py ──────────────────────────────────────────

EXCLUDE_FACTORS = {"industry"}          # extend if you need to hide more later

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

def _fmt_pct(x: float) -> str:
    return f"{x:.1%}"

# ────────────────────────────────────────────────────────────────────
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

def format_stock_metrics(metrics_dict: Dict[str, Union[float, int]], title: str) -> None:
    """
    DEPRECATED: Format stock analysis metrics dictionary into readable output.
    
    This function is deprecated as of [current date] and will be removed in a future version.
    Use display_enhanced_stock_analysis() instead for comprehensive stock analysis display
    that matches the API output format with factor exposures, proxy information, and emojis.
    
    Args:
        metrics_dict: Dictionary of metric names to values
        title: Title for the metrics section
        
    Note:
        This function only displays basic metrics and lacks the rich factor analysis
        capabilities of display_enhanced_stock_analysis().
    """
    import warnings
    warnings.warn("format_stock_metrics() is deprecated. Use display_enhanced_stock_analysis() instead.", 
                  DeprecationWarning, stacklevel=2)
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


def display_enhanced_stock_analysis(analysis_result: Dict[str, Union[str, Dict]], ticker: str) -> None:
    """
    Enhanced CLI display for stock analysis results matching the API display format.
    
    Args:
        analysis_result: Complete analysis result from analyze_stock()
        ticker: Stock ticker symbol
    """
    print("=== STOCK ANALYSIS ===")
    print(f"📈 Stock: {ticker}")
    
    # Volatility metrics
    if "volatility_metrics" in analysis_result:
        vol_metrics = analysis_result["volatility_metrics"]
        if "annual_vol" in vol_metrics:
            vol_annual = vol_metrics["annual_vol"] * 100
            print(f"📊 Annual Volatility: {vol_annual:.1f}%")
        if "monthly_vol" in vol_metrics:
            vol_monthly = vol_metrics["monthly_vol"] * 100
            print(f"📊 Monthly Volatility: {vol_monthly:.1f}%")
    
    # Market regression
    if "regression_metrics" in analysis_result:
        risk = analysis_result["regression_metrics"]
        print(f"\n⚖️  Market Regression:")
        if "beta" in risk:
            print(f"  • Beta: {risk['beta']:.3f}")
        if "alpha" in risk:
            alpha_monthly = risk["alpha"] * 100
            print(f"  • Alpha (Monthly): {alpha_monthly:+.2f}%")
        if "r_squared" in risk:
            r_sq = risk["r_squared"] * 100
            print(f"  • R-Squared: {r_sq:.1f}%")
        if "idio_vol_m" in risk:
            idio_vol = risk["idio_vol_m"] * 100
            print(f"  • Idiosyncratic Vol: {idio_vol:.2f}%")
    elif "risk_metrics" in analysis_result:
        # Fallback for simple analysis
        risk = analysis_result["risk_metrics"]
        print(f"\n⚖️  Market Regression:")
        if "beta" in risk:
            print(f"  • Beta: {risk['beta']:.3f}")
        if "alpha" in risk:
            alpha_monthly = risk["alpha"] * 100
            print(f"  • Alpha (Monthly): {alpha_monthly:+.2f}%")
        if "r_squared" in risk:
            r_sq = risk["r_squared"] * 100
            print(f"  • R-Squared: {r_sq:.1f}%")
        if "idio_vol_m" in risk:
            idio_vol = risk["idio_vol_m"] * 100
            print(f"  • Idiosyncratic Vol: {idio_vol:.2f}%")
    
    # Factor exposures (enhanced display)
    if "factor_exposures" in analysis_result and analysis_result["factor_exposures"]:
        factor_exposures = analysis_result["factor_exposures"]
        print(f"\n🧬 Factor Exposures:")
        
        # Display structured factor data with metadata
        for factor_name, factor_data in factor_exposures.items():
            beta = factor_data.get("beta", 0)
            r_squared = factor_data.get("r_squared", 0) * 100
            print(f"  • {factor_name.title()}: β={beta:.3f} (R²={r_squared:.1f}%)")
    elif "factor_summary" in analysis_result and analysis_result["factor_summary"]:
        # Fallback to legacy factor_summary format
        factor_summary = analysis_result["factor_summary"]
        factor_proxies = analysis_result.get("factor_proxies", {})
        print(f"\n🧬 Factor Exposures:")
        
        if isinstance(factor_summary, list) and factor_proxies:
            # Map list of factor stats to factor names from factor_proxies
            factor_names = list(factor_proxies.keys())
            for i, factor_stats in enumerate(factor_summary):
                if i < len(factor_names) and isinstance(factor_stats, dict):
                    factor_name = factor_names[i]
                    beta = factor_stats.get("beta", 0)
                    r_squared = factor_stats.get("r_squared", 0) * 100
                    print(f"  • {factor_name.title()}: β={beta:.3f} (R²={r_squared:.1f}%)")
        else:
            print(f"  • Raw Factor Summary: {factor_summary}")
    
    # Factor proxies used
    if "factor_exposures" in analysis_result and analysis_result["factor_exposures"]:
        factor_exposures = analysis_result["factor_exposures"]
        print(f"\n🎯 Factor Proxies Used:")
        for factor_name, factor_data in factor_exposures.items():
            proxy = factor_data.get("proxy", "")
            if isinstance(proxy, list):
                proxy_str = ", ".join(proxy[:3])  # Show first 3 if list
                if len(proxy) > 3:
                    proxy_str += f" (+{len(proxy)-3} more)"
                print(f"  • {factor_name.title()}: {proxy_str}")
            else:
                print(f"  • {factor_name.title()}: {proxy}")
    elif "factor_proxies" in analysis_result and analysis_result["factor_proxies"]:
        # Fallback to legacy factor_proxies field
        proxies = analysis_result["factor_proxies"]
        print(f"\n🎯 Factor Proxies Used:")
        for factor, proxy in proxies.items():
            if isinstance(proxy, list):
                proxy_str = ", ".join(proxy[:3])  # Show first 3 if list
                if len(proxy) > 3:
                    proxy_str += f" (+{len(proxy)-3} more)"
                print(f"  • {factor.title()}: {proxy_str}")
            else:
                print(f"  • {factor.title()}: {proxy}")
    
    # Analysis metadata
    if "analysis_metadata" in analysis_result:
        metadata = analysis_result["analysis_metadata"]
        has_factor = metadata.get("has_factor_analysis", False)
        num_factors = metadata.get("num_factors", 0)
        if has_factor:
            print(f"\n📊 Multi-Factor Analysis: ✅ ({num_factors} factors)")
        else:
            print(f"\n📊 Simple Market Analysis: 📈")
    elif analysis_result.get("analysis_type") == "multi_factor":
        factor_count = len(analysis_result.get("factor_proxies", {}))
        print(f"\n📊 Multi-Factor Analysis: ✅ ({factor_count} factors)")
    else:
        print(f"\n📊 Simple Market Analysis: 📈")
    
    print()  # Add blank line after analysis

