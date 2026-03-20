#!/usr/bin/env python
# coding: utf-8
"""
Plaid Integration Loader

This module keeps Plaid normalization and portfolio-conversion logic local to the
monorepo while re-exporting extracted pure API/secrets/connection helpers from
`brokerage.plaid.*` for backward compatibility.
"""

from __future__ import annotations

from brokerage._logging import portfolio_logger
from brokerage.config import AWS_DEFAULT_REGION
from brokerage.plaid.client import (
    client,
    create_client,
    create_hosted_link_token,
    create_update_link_token,
    fetch_plaid_balances,
    fetch_plaid_holdings,
    get_institution_info,
    wait_for_public_token,
)
from brokerage.plaid.connections import remove_plaid_connection, remove_plaid_institution
from brokerage.plaid.secrets import (
    delete_plaid_user_tokens,
    get_plaid_token,
    get_plaid_token_by_item_id,
    list_user_tokens,
    store_plaid_token,
)

# Backward compatibility for consumers importing AWS_REGION from plaid_loader.
AWS_REGION = AWS_DEFAULT_REGION


# In[ ]:


# file: plaid_loader.py

# --- Normalize Holdings Information to Process to YAML ---------------------------------

import pandas as pd

# Import SecurityTypeService for enhanced security classification
try:
    from services.security_type_service import SecurityTypeService
    portfolio_logger.debug("✅ SecurityTypeService successfully imported in plaid_loader")
except ImportError as e:
    SecurityTypeService = None
    portfolio_logger.error(f"❌ SecurityTypeService import failed in plaid_loader: {e}")
    portfolio_logger.warning("⚠️ Falling back to Plaid-only classification (no FMP enhancement)")

def normalize_plaid_holdings(holdings: list, securities: list) -> pd.DataFrame:
    """
    Normalize Plaid holdings and securities data into a structured holdings DataFrame.
    
    Combines two parallel Plaid API payloads:
      • `holdings`: account-specific position details (e.g., quantity, cost basis)
      • `securities`: master security metadata (e.g., ticker, name, type, currency)
    
    For each holding, maps its `security_id` to the corresponding security and merges relevant fields.
    Result is a flat, per-position DataFrame ready for consolidation, risk processing, or YAML export.
    
    Parameters
    ----------
    holdings : list
        List of Plaid `holdings` objects (from `/investments/holdings/get`).
    securities : list
        List of Plaid `securities` objects (from the same endpoint).
    
    Returns
    -------
    pd.DataFrame
        Normalized holdings with one row per security position.
        Includes columns: ticker, name, quantity, price, value, cost_basis, type, currency, account_id.
    
    Notes
    -----
    • Defaults missing currencies to 'USD'  
    • If `security_id` lookup fails, fields from `securities` will be empty in that row
    """
    from utils.logging import log_alert
    from utils.ticker_resolver import resolve_fmp_ticker

    sec_map = {s["security_id"]: s for s in securities}
    rows = []

    for h in holdings:
        s = sec_map.get(h["security_id"], {})
        ticker_symbol = s.get("ticker_symbol")
        if not ticker_symbol:
            log_alert(
                "plaid_missing_ticker_symbol",
                "medium",
                "Plaid holding missing ticker symbol",
                source="plaid_holdings",
                details={
                    "security_id": h.get("security_id"),
                    "account_id": h.get("account_id"),
                    "security_name": s.get("name"),
                    "security_type": s.get("type"),
                },
            )
        # Extract exchange MIC code (ISO-10383) for proper ticker resolution
        exchange_mic = s.get("market_identifier_code")
        currency = h.get("iso_currency_code") or s.get("iso_currency_code", "USD")
        position_type = s.get("type")

        fmp_ticker = None
        if ticker_symbol and position_type != "cash" and not ticker_symbol.startswith("CUR:"):
            fmp_ticker = resolve_fmp_ticker(
                ticker=ticker_symbol,
                company_name=s.get("name"),
                currency=currency,
                exchange_mic=exchange_mic,
            )
        else:
            fmp_ticker = ticker_symbol

        rows.append({
            "ticker":     ticker_symbol,
            "fmp_ticker": fmp_ticker,
            "name":       s.get("name"),
            "quantity":   h.get("quantity"),
            "price":      h.get("institution_price"),
            "value":      h.get("institution_value"),
            "cost_basis": h.get("cost_basis"),
            "type":       position_type,
            "currency":   currency,
            "cusip":      s.get("cusip"),
            "isin":       s.get("isin"),
            "is_cash_equivalent": s.get("is_cash_equivalent"),
            "account_id": h.get("account_id"),
            "exchange_mic": exchange_mic,  # ISO-10383 Market Identifier Code (e.g., "XLON" for London)
        })

    return pd.DataFrame(rows)


# In[ ]:


# file: plaid_loader.py

# --- Infer Margin Balances ---------------------------------

import pandas as pd
import numpy as np


def calc_cash_gap(df_acct: pd.DataFrame, balances: dict, tol: float = 0.01) -> float:
    """
    Return the cash / margin gap for *one* Plaid account.

    gap  > 0  → idle cash the API did NOT put in holdings  
    gap  < 0  → margin debit (or overdraft) the API did NOT put in holdings

    Parameters
    ----------
    df_acct  : normalised holdings for ONE account  (output of normalize_plaid_holdings)
    balances : balances block from Plaid (account.balances.to_dict())
    tol      : ignore gaps smaller than this absolute value (defaults to 1 ¢)

    Returns
    -------
    float   (0.0 if |gap| < tol)
    """
    pos_total   = df_acct["value"].sum(skipna=True)
    acct_total  = float(balances.get("current", 0.0))
    gap = round(acct_total - pos_total, 2)          # round for cleanliness

    return 0.0 if abs(gap) < tol else gap

def append_cash_gap(df_acct: pd.DataFrame, gap: float, balances: dict) -> pd.DataFrame:
    """
    Appends a synthetic 'cash' or 'margin debit' row to a normalized holdings DataFrame 
    if a non-zero gap is detected between account balance and reported holdings value.

    Parameters
    ----------
    df_acct : pd.DataFrame
        Normalized holdings for a single account (output of `normalize_plaid_holdings`).
        Must include columns: ticker, value, type, account_id, etc.
    gap : float
        Difference between balances["current"] and df_acct["value"].sum(). 
        Positive = idle cash; negative = margin loan or overdraft.
    balances : dict
        Account-level Plaid balances block (from balances_data["accounts"][i]["balances"]).
        Used to determine the currency for the synthetic row.

    Returns
    -------
    pd.DataFrame
        The original DataFrame with an added synthetic row if gap ≠ 0. 
        Returns unchanged DataFrame if gap is zero.

    Notes
    -----
    • The synthetic row uses ticker format "CUR:<currency>" (e.g., "CUR:USD")
    • Row is padded to match the input DataFrame's schema and dtypes.
    • Handles edge cases where Plaid omits cash or margin positions from holdings.
    • Ensures compatibility with `pd.concat` by filtering all-NA columns from patch row.
    """
    if gap == 0.0:
        return df_acct

    currency = balances.get("iso_currency_code", "USD")
    if not currency:
        currency = "USD"
        portfolio_logger.warning("Missing currency in Plaid balances. Defaulting to 'USD'.")
        
    synthetic_row = {
        "ticker":     f"CUR:{currency}",
        "name":       "Synthetic cash" if gap > 0 else "Synthetic margin debit",
        "quantity":   float(gap),
        "price":      1.0,
        "value":      float(gap),
        "cost_basis": None,
        "type":       "cash",
        "currency":   currency,
        "account_id": df_acct["account_id"].iloc[0] if "account_id" in df_acct else None,
    }

    # Match all columns and pad with exact dtypes
    row = {}
    for col in df_acct.columns:
        if col in synthetic_row:
            row[col] = synthetic_row[col]
        else:
            dtype = df_acct[col].dtype
            row[col] = np.nan if pd.api.types.is_numeric_dtype(dtype) else None

    # Avoid pandas all-NA concat deprecation by excluding columns that are
    # all-NA in existing rows and in the synthetic row payload.
    append_cols = [
        col for col in df_acct.columns
        if not (df_acct[col].isna().all() and pd.isna(row.get(col)))
    ]
    combined = df_acct[append_cols].copy()
    # pandas may emit a deprecation warning from internal concat logic here
    # when extension dtypes are involved; assignment semantics are unchanged.
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated.*",
            category=FutureWarning,
        )
        combined.loc[len(combined)] = {col: row.get(col) for col in append_cols}
    return combined

def should_skip_cash_patch(df_acct: pd.DataFrame) -> bool:
    """
    Skip synthetic cash/margin injection if Plaid already reported
    a position with type == 'cash'.
    """
    return df_acct["type"].eq("cash").any()

def patch_cash_gap_from_balance(
    df_acct: pd.DataFrame,
    balances: dict,
    *,
    institution: str = "UNKNOWN",
    verbose: bool = False
) -> pd.DataFrame:
    """
    Detects and appends synthetic cash/margin row to one account's holdings DataFrame
    using balances.current vs sum of reported positions.

    Parameters
    ----------
    df_acct : pd.DataFrame
        Normalized holdings for one account (from normalize_plaid_holdings).
    balances : dict
        Account-level Plaid balances (from balances_data["accounts"][i]["balances"]).
    verbose : bool
        If True, prints gap detection and patch action.

    Returns
    -------
    pd.DataFrame
        Holdings with synthetic cash row added if a material gap is detected.
    """
    gap = calc_cash_gap(df_acct, balances)

    # ── STEP 0: bail out if Plaid already sent a 'cash' position ───────────
    if should_skip_cash_patch(df_acct):
        if verbose:
            portfolio_logger.debug(f"[{institution}] Margin Calculation: Skipped — 'cash' present in holdings. Balance / Holdings Difference: {gap:,.2f}")
        return df_acct
        
    # ── STEP 1: calculate the gap ──────────────────────────────────────────
    if verbose:
        tag = "idle cash" if gap > 0 else "margin debit" if gap < 0 else "balanced"
        portfolio_logger.debug(f"[{institution}] Margin calculation: Balance / Holdings Cash Difference: {gap:,.2f} → {tag}")
    return append_cash_gap(df_acct, gap, balances)


# In[ ]:


# file: plaid_loader.py

# --- Map Cash to ETF Proxies ---------------------------------
from pathlib import Path
import yaml
import pandas as pd
from config import resolve_config_path

# ---------------------------------------------------------------------
def _load_maps(yaml_path: str | Path = "cash_map.yaml") -> tuple[dict, dict]:
    """
    Load cash proxy mapping definitions from a local YAML file.
    
    Reads a YAML file containing:
      • `proxy_by_currency`: maps currency codes to ETF tickers (e.g., USD → SGOV)
      • `alias_to_currency`: maps ticker-like aliases to canonical currency codes (e.g., CUR:USD → USD)
    
    Used internally by `map_cash_to_proxy()` to resolve how synthetic or raw cash positions
    should be mapped to tradable proxy tickers.
    
    Parameters
    ----------
    yaml_path : str or Path, optional
        Path to the YAML config file (default: "cash_map.yaml").
    
    Returns
    -------
    tuple[dict, dict]
        A tuple of two dictionaries:
          - proxy_by_currency: currency → ETF proxy
          - alias_to_currency: alias → canonical currency
    """
    resolved_path = resolve_config_path(str(yaml_path))
    cfg = yaml.safe_load(resolved_path.read_text()) if resolved_path.is_file() else {}
    proxy_by   = {k.upper(): v for k, v in cfg.get("proxy_by_currency", {}).items()}
    alias_to   = {k.upper(): v.upper() for k, v in cfg.get("alias_to_currency", {}).items()}
    return proxy_by, alias_to


# ---------------------------------------------------------------------
def map_cash_to_proxy(df: pd.DataFrame, yaml_path: str = "cash_map.yaml") -> pd.DataFrame:
    """
    Replace raw or synthetic cash tickers in a holdings DataFrame with tradable ETF proxies.
    
    **USAGE NOTE:** This function is only used for YAML fallback file generation.
    The main backend processing pipeline uses `convert_plaid_holdings_to_portfolio_data()`
    which bypasses YAML conversion entirely.
    
    Uses a currency-to-proxy map and a set of known ticker aliases to:
      • Identify cash rows (e.g., "CUR:USD", "USD CASH")
      • Replace their tickers with the appropriate proxy (e.g., SGOV for USD)
      • Collapse duplicate proxy tickers by summing 'value' and 'quantity'
      • Preserve all other metadata from the first occurrence
    
    Intended as a post-processing step after loading and patching Plaid holdings.
    
    Parameters
    ----------
    df : pd.DataFrame
        Normalized holdings DataFrame with at least: 'ticker', 'value', 'quantity'.
    yaml_path : str, optional
        Path to YAML file with mapping config (default: "cash_map.yaml").
    
    Returns
    -------
    pd.DataFrame
        Updated holdings with cash positions replaced by ETF proxies.
        If no mappings apply, returns the original DataFrame unchanged.
    
    Notes
    -----
    • First-seen metadata is retained when collapsing rows  
    • No mapping is performed if the YAML file is missing or empty
    • Only called internally by `convert_plaid_df_to_yaml_input()`
    """
    proxy_by_ccy, alias_to_ccy = _load_maps(yaml_path)
    if not alias_to_ccy or not proxy_by_ccy:
        return df                     # nothing to map

    df = df.copy()

    # --- replace alias tickers with proxy tickers -------------------------
    tickers_uc = df["ticker"].astype(str).str.upper()
    for idx, alias in enumerate(tickers_uc):
        if alias not in alias_to_ccy:
            continue
        ccy   = alias_to_ccy[alias]
        proxy = proxy_by_ccy.get(ccy)
        if proxy:
            df.at[idx, "ticker"] = proxy
            df.at[idx, "name"]   = "Cash proxy"
            df.at[idx, "type"]   = "cash_proxy"

    # --- collapse proxy duplicates: same ticker → sum 'value' and 'quantity' ---
    cash_proxies = set(proxy_by_ccy.values())          # {'SGOV', 'ESTR', ...}
    dup_mask     = df["ticker"].isin(cash_proxies) & df.duplicated("ticker")
    
    if dup_mask.any():
        summed = (
            df.groupby("ticker", as_index=False)[["value", "quantity"]]
              .sum()
              .rename(columns={"value": "_new_val", "quantity": "_new_qty"})
        )
    
        # keep first row per ticker, drop others
        df = df.drop_duplicates("ticker", keep="first")
    
        # update with aggregated sums
        df = df.merge(summed, on="ticker", how="left")
        df["value"]    = df["_new_val"].fillna(df["value"])
        df["quantity"] = df["_new_qty"].fillna(df["quantity"])
    
        df.drop(columns=["_new_val", "_new_qty"], inplace=True)

    return df.reset_index(drop=True)


# In[ ]:


# file: plaid_loader.py

# --- Write holdings to portfolio.yaml ---------------------------------
import yaml
import pandas as pd
from settings import PORTFOLIO_DEFAULTS

def convert_plaid_df_to_yaml_input(
    df: pd.DataFrame,
    output_path: str = "portfolio.yaml",
    yaml_path: str = "cash_map.yaml",
    *,
    dates: dict | None = None,
) -> None:
    """
    Build a portfolio.yaml from a normalized holdings DataFrame.
    
    **USAGE NOTE:** This function is only used for YAML fallback file generation
    in `routes/plaid.py`. The main backend processing pipeline uses
    `convert_plaid_holdings_to_portfolio_data()` which creates PortfolioData objects
    directly, bypassing YAML conversion entirely.

    This function:
    • Automatically maps synthetic/raw cash tickers (e.g., CUR:USD) to ETF proxies (e.g., SGOV)
    • Consolidates each holding into either shares or dollar exposure
    • Skips derivatives and any positions with missing tickers

    Parameters
    ----------
    df : pd.DataFrame
        Consolidated holdings DataFrame (after normalization + patching).
    output_path : str
        File path to write the YAML output.
    yaml_path : str
        Path to the cash_map.yaml file for currency→ETF proxy mapping.
    dates : dict | None
        Optional override for portfolio start/end dates.
        Falls back to PORTFOLIO_DEFAULTS if not provided.
    
    Example
    -------
    >>> convert_plaid_df_to_yaml_input(
            df_consolidated,
            output_path="portfolio.yaml",
            yaml_path="config/mappings/cash_map.yaml"
        )

    >>> convert_plaid_df_to_yaml_input(
            df_consolidated,
            dates={"start_date": "2020-01-01", "end_date": "2025-12-31"}
        )
        
    See Also
    --------
    convert_plaid_holdings_to_portfolio_data : Main function used by backend processing
    """
    df = map_cash_to_proxy(df, yaml_path=yaml_path)
    
    dates = dates or PORTFOLIO_DEFAULTS
    portfolio_input: dict[str, dict[str, float]] = {}

    for _, row in df.iterrows():
        ticker = row["ticker"]
        qty    = row.get("quantity")
        val    = row.get("value")

        if pd.isna(ticker) or row.get("type") == "derivative":
            continue

        if pd.notna(qty) and qty > 0:
            portfolio_input[ticker] = {"shares": float(qty)}
        else:
            portfolio_input[ticker] = {"dollars": float(val)}

    config = {
        "portfolio_input":      portfolio_input,
        "start_date":           dates["start_date"],
        "end_date":             dates["end_date"],
        "expected_returns":     {},
        "stock_factor_proxies": {}
    }

    with open(output_path, "w") as f:
        yaml.dump(config, f, sort_keys=False)

    print(f"✅ YAML written to {output_path}")


# In[ ]:


# file: plaid_loader.py

# --- RUNNER: Load all holdings with Plaid ---------------------------------

def load_all_user_holdings(user_id: str, region_name: str, client: plaid_api.PlaidApi) -> pd.DataFrame:
    """
    Fetch and normalize Plaid investment holdings across all institutions for a user,
    with account-level cash gap detection and synthetic cash/margin patching.

    For each institution linked to the user:
      • Retrieves long-lived Plaid access token from AWS Secrets Manager
      • Fetches both investment holdings and account balances
      • Loops through each individual account in balances payload
      • Normalizes holdings at the account level (via `normalize_plaid_holdings`)
      • Applies synthetic 'cash' or 'margin' rows if Plaid omits them (via `patch_cash_gap_from_balance`)
      • Tags each row with institution name for downstream attribution

    Parameters
    ----------
    user_id : str
        Unique user identifier (used in Secrets Manager path, e.g., email address)
    region_name : str
        AWS region to locate Plaid access tokens (e.g., 'us-east-1')
    client : plaid_api.PlaidApi
        Initialized Plaid API client instance

    Returns
    -------
    pd.DataFrame
        Combined and fully normalized holdings across all institutions and accounts,
        including inferred synthetic cash/margin rows where appropriate.
        Columns include: ticker, quantity, value, type, account_id, institution, etc.

    Notes
    -----
    • Uses `list_user_tokens()` to iterate over all institutions linked to the user.
    • Cash patching is skipped if Plaid already reports a 'cash' holding.
    • Output is suitable for direct export to `portfolio.yaml` or risk processing.
    • If no valid accounts or holdings exist, returns an empty DataFrame.
    """
    all_tokens = list_user_tokens(user_id, region_name)
    dfs = []

    for secret_path in all_tokens:
        token_data = get_plaid_token(
            user_id=user_id,
            institution=secret_path.split("/")[-1].replace("-", " ").title(),
            region_name=region_name
        )
        access_token = token_data["access_token"]
        holdings_data = fetch_plaid_holdings(access_token, client)
        balances_data = fetch_plaid_balances(access_token, client)

        # Patch each account separately
        for acct in balances_data["accounts"]:
            acct_id  = acct["account_id"]
            acct_bal = acct["balances"]

            # Filter only holdings for this account
            h = [x for x in holdings_data["holdings"] if x["account_id"] == acct_id]
            s = holdings_data["securities"]
            if not h:
                continue  # skip empty

            df = normalize_plaid_holdings(h, s)
            df = patch_cash_gap_from_balance(
                df, 
                acct_bal, 
                institution=token_data["institution"],
                verbose=True)

            df["institution"] = token_data["institution"]
            df["account_name"] = acct.get("official_name") or acct.get("name")

            dfs.append(df)

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# In[ ]:


# file: plaid_loader.py

# --- Consolidate holdings by ticker ---
def consolidate_holdings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Consolidate holdings across multiple accounts or institutions into a single per-ticker view.
    
    Sums `quantity` and `value` for each unique ticker across the input holdings DataFrame,
    and merges the first-seen metadata fields (e.g., name, type, account_id, etc.) for each ticker.
    Intended for use after normalizing and mapping Plaid holdings.
    
    Parameters
    ----------
    df : pd.DataFrame
        Normalized holdings DataFrame, possibly from multiple accounts or institutions.
        Must contain at least the columns: 'ticker', 'quantity', and 'value'.
    
    Returns
    -------
    pd.DataFrame
        Consolidated holdings with one row per ticker, including:
        • Aggregated 'quantity' and 'value'
        • Metadata from the first occurrence of each ticker
        • All other non-numeric columns preserved from the first occurrence
    
    Notes
    -----
    ▸ Rows with missing tickers are excluded.  
    ▸ Sorting ensures deterministic metadata retention when duplicates exist.
    """
    if "local_price" not in df.columns:
        df["local_price"] = df.get("price")
    if "local_value" not in df.columns:
        df["local_value"] = df.get("value")

    # 1. Sum quantity + value
    sums = (
        df.dropna(subset=["ticker"])
          .groupby("ticker", as_index=False)[["quantity", "value", "local_value"]]
          .sum()
    )

    # 2. Get first row per ticker for metadata
    firsts = (
        df.dropna(subset=["ticker"])
          .sort_values("ticker")  # ensure deterministic
          .drop_duplicates("ticker", keep="first")
          .set_index("ticker")
    )

    # 3. Merge sum + metadata
    return sums.set_index("ticker").join(
        firsts.drop(columns=["quantity", "value", "local_value"]), how="left"
    ).reset_index()


# In[ ]:

# ═══════════════════════════════════════════════════════════════════════════════
# 🔄 TYPE MAPPING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _map_plaid_type_to_internal(plaid_type: str) -> str:
    """
    Map Plaid's security types using centralized mappings.
    
    CENTRALIZED MAPPING SYSTEM:
    Uses the established 3-tier architecture pattern (Database → YAML → Hardcoded)
    that is consistent with all other mapping systems in the risk module.
    
    THREE-LAYER TYPE SYSTEM:
    1. Plaid Raw: type ("fixed income", "mutual fund", "equity")
    2. This Function: Maps type → internal type ("fixed income" → "bond") via centralized system
    3. Our System: Uses internal type for logic (cash mapping, database storage)
    
    SUPPORTED MAPPINGS (via centralized system):
    - "fixed income" → "bond" (Bonds and CDs)
    - "mutual fund" → "mutual_fund" (Pooled funds)
    - "cash" → "cash" (Cash and money market)
    - "equity" → "equity" (Stocks - may be enhanced with FMP)
    - "etf" → "etf" (Exchange-traded funds)
    - "cryptocurrency" → "crypto" (Digital currencies)
    - "derivative" → "derivative" (Options, warrants)
    - "loan" → "bond" (Loans treated as fixed income)
    - "other" → "other" (Unknown types)
    
    ARCHITECTURE:
    Calls utils.security_type_mappings.map_plaid_type() which uses:
    1. Database: security_type_mappings table (primary)
    2. YAML: security_type_mappings.yaml (fallback)
    3. Hardcoded: Built-in mapping dictionary (ultimate fallback)
    
    Args:
        plaid_type: Plaid security type (fixed income, mutual fund, equity, etc.)
        
    Returns:
        Our internal type classification (bond, mutual_fund, equity, etc.)
        Preserves original type if unknown to maintain provider expertise
    """
    from utils.security_type_mappings import map_plaid_type
    
    # Use centralized mapping system
    mapped_type = map_plaid_type(plaid_type)
    if mapped_type:
        portfolio_logger.debug(f"✅ Plaid centralized mapping: {plaid_type} → {mapped_type}")
        return mapped_type
    else:
        # Log unknown type and return the original type as-is to preserve provider expertise
        portfolio_logger.warning(f"⚠️ Unknown Plaid type '{plaid_type}', using as-is")
        return plaid_type.lower().replace(' ', '_')

# Asset class mapping function moved to SecurityTypeService._map_security_type_to_asset_class()
# for cleaner architecture and centralized logic

def get_enhanced_security_type(ticker: str, original_type: str) -> str:
    """
    Get security type with Plaid preservation and centralized mapping integration.
    
    CENTRALIZED MAPPING INTEGRATION (Updated):
    Uses the established 3-tier architecture pattern (Database → YAML → Hardcoded)
    that is consistent with all other mapping systems in the risk module.
    ALL types are first mapped to canonical types via _map_plaid_type_to_internal().
    
    PLAID PRESERVE_NON_EQUITY STRATEGY (with Canonical Mapping):
    1. All types: First mapped to canonical types ("fixed income" → "bond")
    2. Non-equity types: Preserve mapped canonical type (no FMP needed)
    3. Equity types: Use centralized SecurityTypeService with FMP API (to distinguish stocks vs funds)
    
    ARCHITECTURE:
    1. Calls utils.security_type_mappings.should_preserve_plaid_type() for strategy
    2. If preserve: Maps via _map_plaid_type_to_internal() and returns canonical type
    3. If enhance: Uses SecurityTypeService with FMP API for precise classification
    4. Fallback: Hardcoded preserve logic with canonical mapping
    
    PROBLEM SOLVED:
    - Maps all Plaid types to canonical types for consistency
    - Preserves Plaid's good classifications after mapping ("fixed income" → "bond")
    - Only uses FMP for ambiguous "equity" classifications
    - Reduces unnecessary FMP API calls
    - Maintains provider expertise where they excel
    - Ensures database stores canonical types consistently
    
    Args:
        ticker: Security ticker symbol (e.g., 'TLT', 'SPY', 'AAPL')
        original_type: Original security type from Plaid provider (e.g., "fixed income", "mutual fund")
        
    Returns:
        Enhanced security type (canonical): 'bond', 'equity', 'etf', 'mutual_fund', 'cash', etc.
        
    Examples:
        >>> get_enhanced_security_type('TLT', 'fixed income')
        'bond'  # Plaid type mapped to canonical via centralized system
        >>> get_enhanced_security_type('DSU', 'mutual fund')
        'mutual_fund'  # Plaid type mapped to canonical via centralized system
        >>> get_enhanced_security_type('AAPL', 'equity') 
        'equity'  # FMP confirms it's a stock via centralized system
        >>> get_enhanced_security_type('SPY', 'equity')
        'etf'  # FMP corrects Plaid's misclassification via centralized system
    """
    try:
        from utils.security_type_mappings import should_preserve_plaid_type
        
        # Check centralized system for preserve strategy
        should_preserve = should_preserve_plaid_type(original_type)
        
        if should_preserve:
            # Map to canonical type before preserving
            mapped_type = _map_plaid_type_to_internal(original_type)
            portfolio_logger.debug(f"🔒 Centralized system: Preserving Plaid classification for {ticker}: {original_type} → {mapped_type}")
            return mapped_type  # ✅ Preserve provider classification via centralized decision (mapped to canonical)
        
        # Only use SecurityTypeService for types that shouldn't be preserved (typically "equity")
        portfolio_logger.debug(f"🔍 Centralized system: Plaid classified {ticker} as '{original_type}' - checking with FMP for precise classification")
        
    except Exception as e:
        # Fallback to original hardcoded logic if centralized system fails
        portfolio_logger.warning(f"⚠️ Centralized mapping system unavailable: {e}, using hardcoded preserve logic")
        
        # Preserve all Plaid types EXCEPT "equity" - Plaid has good classification for these
        if original_type != 'equity':
            # Map to canonical type before preserving (even in fallback)
            mapped_type = _map_plaid_type_to_internal(original_type)
            portfolio_logger.debug(f"🔒 Hardcoded fallback: Preserving Plaid classification for {ticker}: {original_type} → {mapped_type} (non-equity type)")
            return mapped_type  # ✅ Preserve provider classification (mapped to canonical)
        
        portfolio_logger.debug(f"🔍 Hardcoded fallback: Plaid classified {ticker} as 'equity' - checking with FMP for precise classification")
    
    try:
        # Use SecurityTypeService static method for equity securities (takes list of tickers)  
        security_types = SecurityTypeService.get_security_types([ticker])
        enhanced_type = security_types.get(ticker)  # Don't pass fallback - let it be None if not found
        
        # If SecurityTypeService found a classification, use it; otherwise keep original type
        if enhanced_type:
            # Log when enhancement changes the classification
            if enhanced_type != original_type:
                portfolio_logger.info(f"✨ SecurityTypeService enhanced {ticker}: {original_type} → {enhanced_type}")
            else:
                portfolio_logger.debug(f"✅ FMP confirmed {ticker} classification: {enhanced_type}")
            return enhanced_type
        else:
            # SecurityTypeService had no data - keep original type
            portfolio_logger.warning(f"⚠️ FMP has no data for {ticker}, keeping Plaid classification: {original_type}")
            return original_type
        
    except Exception as e:
        portfolio_logger.error(f"❌ SecurityTypeService failed for {ticker}: {e}, falling back to Plaid type: {original_type}")
        return original_type


def convert_plaid_holdings_to_portfolio_data(holdings_df, user_email, portfolio_name):
    """
    Convert Plaid holdings DataFrame to PortfolioData object.
    
    CASH vs SECURITIES HANDLING:
    - Cash positions (type='cash'): Stored as {'dollars': value}
    - Securities: Stored as {'shares': quantity} (allows negative for shorts)
    - Uses Plaid's type classification for position identification
    
    MIXED CURRENCY HANDLING:
    - PortfolioData sums shares/dollars across currencies (currency ignored by analysis)
    - Currency field set to 'MIXED' when consolidating across different currencies
    - First currency preserved for single-currency positions
    - Logs mixed currency summing for transparency
    - No ticker mutation (preserves clean tickers for factor mapping)
    
    PLAID INTEGRATION:
    - Preserves Plaid account_id and cost_basis metadata
    - Works with any Plaid broker format (CUR:USD, CASH_USD, etc.)
    - Cash positions later mapped by portfolio_manager (CUR:USD → SGOV)
    - Persists name/brokerage_name/account_name for cache fidelity
    
    Args:
        holdings_df: DataFrame with Plaid holdings data
        user_email: User email for database operations
        portfolio_name: Name of the portfolio to create
        
    Returns:
        PortfolioData: Portfolio data object ready for analysis
    """
    from portfolio_risk_engine.data_objects import PortfolioData
    from datetime import datetime
    import pandas as pd
    
    # Create portfolio input dictionary
    portfolio_input = {}
    fmp_ticker_map = {}
    
    # Track mixed currencies for logging (same as SnapTrade behavior)
    ticker_currencies = {}
    for _, row in holdings_df.iterrows():
        ticker = row.get('ticker', '')
        currency = row.get('currency', 'USD')

        if ticker not in ticker_currencies:
            ticker_currencies[ticker] = set()
        ticker_currencies[ticker].add(currency)
    
    # Log mixed currency info (consistent with SnapTrade)
    from utils.logging import log_event
    for ticker, currencies in ticker_currencies.items():
        if len(currencies) > 1:
            log_event(
                "plaid_mixed_currency_summing",
                "Mixed currency holdings summed for portfolio conversion",
                ticker=ticker,
                currencies=list(currencies),
                behavior="sum_shares",
            )
    
    # Process each holding - sum shares for same ticker across currencies
    for _, row in holdings_df.iterrows():
        ticker = row.get('ticker', '')
        quantity = row.get('quantity', 0)
        value = row.get('value', 0)
        currency = row.get('currency', 'USD')  # Extract currency from DataFrame
        cost_basis = row.get('cost_basis')
        account_id = row.get('account_id')
        name = row.get('name') or ticker
        brokerage_name = row.get('brokerage_name') or row.get('institution')
        account_name = row.get('account_name')
        position_type = row.get('type')  # NO DEFAULTS! Preserve what Plaid actually said
        
        fmp_ticker = row.get('fmp_ticker')
        if isinstance(fmp_ticker, str) and fmp_ticker.strip():
            existing_fmp = fmp_ticker_map.get(ticker)
            if existing_fmp and existing_fmp != fmp_ticker:
                raise ValueError(f"Conflicting fmp_ticker for {ticker}: {existing_fmp} vs {fmp_ticker}")
            fmp_ticker_map[ticker] = fmp_ticker

        # Use Plaid's type classification to identify cash positions
        # This works for any broker format (CUR:USD, CASH_USD, etc.)
        if position_type == 'cash':
            if ticker in portfolio_input:
                # Sum cash values across currencies
                portfolio_input[ticker]['dollars'] += float(value)
                if not portfolio_input[ticker].get('name') and name:
                    portfolio_input[ticker]['name'] = name
                if not portfolio_input[ticker].get('brokerage_name') and brokerage_name:
                    portfolio_input[ticker]['brokerage_name'] = brokerage_name
                if not portfolio_input[ticker].get('account_name') and account_name:
                    portfolio_input[ticker]['account_name'] = account_name
                # Mark as mixed if currencies differ
                existing_currency = portfolio_input[ticker].get('currency')
                if existing_currency != currency:
                    portfolio_input[ticker]['currency'] = 'MIXED'
            else:
                portfolio_input[ticker] = {
                    'dollars': float(value),  # Store as dollars, not shares
                    'currency': currency,
                    'type': 'cash',
                    'account_id': account_id,
                    'name': name,
                    'brokerage_name': brokerage_name,
                    'account_name': account_name
                }
        else:
            if ticker in portfolio_input:
                # Sum shares (currency doesn't matter for PortfolioData analysis)
                portfolio_input[ticker]['shares'] += float(quantity)
                # Sum cost_basis when consolidating same ticker
                # Use pd.notna() to catch both None and NaN (NaN + x = NaN would poison the sum)
                if pd.notna(cost_basis):
                    existing_cost = portfolio_input[ticker].get('cost_basis')
                    if pd.notna(existing_cost):
                        portfolio_input[ticker]['cost_basis'] = existing_cost + cost_basis
                    else:
                        portfolio_input[ticker]['cost_basis'] = cost_basis
                else:
                    # Warn about missing cost_basis (not expected for non-cash positions)
                    log_event(
                        "plaid_missing_cost_basis",
                        "Missing cost_basis during portfolio conversion",
                        ticker=ticker,
                    )
                # Mark as mixed if currencies differ
                existing_currency = portfolio_input[ticker].get('currency')
                if existing_currency != currency:
                    portfolio_input[ticker]['currency'] = 'MIXED'
                if not portfolio_input[ticker].get('name') and name:
                    portfolio_input[ticker]['name'] = name
                if not portfolio_input[ticker].get('brokerage_name') and brokerage_name:
                    portfolio_input[ticker]['brokerage_name'] = brokerage_name
                if not portfolio_input[ticker].get('account_name') and account_name:
                    portfolio_input[ticker]['account_name'] = account_name
                if fmp_ticker_map.get(ticker) and 'fmp_ticker' not in portfolio_input[ticker]:
                    portfolio_input[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
            else:
                portfolio_input[ticker] = {
                    'shares': float(quantity),
                    'currency': currency,  # Preserve currency from Plaid
                    'type': get_enhanced_security_type(ticker, position_type),  # ← ENHANCEMENT: Canonical mapping + selective FMP classification
                    'cost_basis': cost_basis,
                    'account_id': account_id,
                    'name': name,
                    'brokerage_name': brokerage_name,
                    'account_name': account_name
                }
                if fmp_ticker_map.get(ticker):
                    portfolio_input[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
    
    # Create factor proxies (placeholder - actual assignment handled by analysis components)
    stock_factor_proxies = {}
    
    # Create PortfolioData object using from_holdings method
    from datetime import datetime
    
    # Use centralized dates from settings.py
    from settings import PORTFOLIO_DEFAULTS
    
    portfolio_data = PortfolioData.from_holdings(
        holdings=portfolio_input,
        start_date=PORTFOLIO_DEFAULTS["start_date"],
        end_date=PORTFOLIO_DEFAULTS["end_date"],
        portfolio_name=portfolio_name,
        fmp_ticker_map=fmp_ticker_map or None,
    )
    
    # Set the complex factor proxies structure manually
    portfolio_data.stock_factor_proxies = stock_factor_proxies
    
    # Add metadata
    portfolio_data.import_source = 'plaid'
    portfolio_data.import_date = datetime.now().isoformat()
    portfolio_data.user_email = user_email
    
    return portfolio_data
