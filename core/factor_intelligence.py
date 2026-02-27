"""
Factor Intelligence Core

Core helpers for building the factor ETF universe and the aligned monthly
returns panel with robust caching. These functions are shared by services and
routers to avoid re-implementing data assembly logic.

Key functions
-------------
- load_asset_class_proxies(): DB‑first loader for asset class → ETF proxies
- load_industry_buckets(): DB‑first loader for industry → sector_group mapping
- fetch_factor_universe(): Build deterministic, categorized ETF universe
- build_factor_returns_panel(): Construct aligned monthly returns matrix

Notes
-----
- Prefers dividend‑adjusted total‑return series; falls back to close.
- Deterministic universe hashing aids cache keys and debugging.
- Uses global LRU cache sizes from utils.config.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time
import json
import hashlib
import numpy as np

import pandas as pd

from utils.config import DATA_LOADER_LRU_SIZE
from utils.logging import log_portfolio_operation, log_critical_alert


def _get_ticker_source_file(ticker: str, category: str) -> str:
    """Determine which configuration file a ticker likely comes from based on category."""
    if category == "industry":
        return "industry_to_etf.yaml"
    elif category in ["style", "market"]:
        return "exchange_etf_proxies.yaml"
    elif category == "cash":
        return "cash_map.yaml"
    elif category in ["bond", "commodity", "crypto"]:
        return "asset_etf_proxies.yaml"
    else:
        return "unknown_source"


from portfolio_risk import calculate_portfolio_performance_metrics

from data_loader import (
    fetch_monthly_total_return_price,
    fetch_monthly_close,
)
from factor_utils import calc_monthly_returns
from settings import RATE_FACTOR_CONFIG, FACTOR_INTELLIGENCE_DEFAULTS

# Reuse existing DB‑first YAML loaders for exchange/industry maps
from proxy_builder import load_exchange_proxy_map, load_industry_etf_map

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def load_asset_class_proxies() -> Tuple[Dict[str, Dict[str, str]], str]:
    """
    Load asset class → ETF proxies using DB‑first approach, with YAML and
    hardcoded fallbacks.

    Returns
    -------
    (proxies, source):
        proxies: {asset_class: {proxy_key: etf_ticker}}
        source:  'database' | 'yaml' | 'hardcoded'
    """
    # DB‑first
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            proxies = db_client.get_asset_etf_proxies()
        if proxies:
            return proxies, 'database'
    except Exception as e:
        log_portfolio_operation("asset_proxy_loader_db_failed", {"error": str(e)}, execution_time=0)

    # YAML fallback
    try:
        import yaml
        yaml_path = _PROJECT_ROOT / "asset_etf_proxies.yaml"
        if yaml_path.exists():
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            # Expect structure {asset_classes: {class: {canonical: {key: ticker}}}}
            out: Dict[str, Dict[str, str]] = {}
            classes = (data or {}).get('asset_classes', {})
            for aclass, section in classes.items():
                canon = section.get('canonical', {}) if isinstance(section, dict) else {}
                if canon:
                    out[aclass] = {k: str(v) for k, v in canon.items()}
            if out:
                return out, 'yaml'
    except Exception as e:
        log_portfolio_operation("asset_proxy_loader_yaml_failed", {"error": str(e)}, execution_time=0)

    # Minimal hardcoded fallback
    return {
        'bond':      {'UST2Y': 'SHY', 'UST10Y': 'IEF', 'UST30Y': 'TLT'},
        'commodity': {'broad': 'DBC', 'gold': 'GLD'},
        'crypto':    {'BTC': 'IBIT'}
    }, 'hardcoded'


@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def load_industry_buckets() -> Dict[str, str]:
    """
    Load industry → sector_group buckets (DB‑first). Industries with NULL bucket
    are omitted; callers can fall back to per‑industry granularity.
    """
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_industry_sector_groups()
    except Exception:
        # No YAML for buckets by design; return empty mapping
        return {}


@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def load_cash_proxies() -> Tuple[Dict[str, str], str]:
    """
    Load cash currency → ETF proxy mappings (DB‑first, YAML fallback).

    Returns (mapping, source) where mapping is {currency: proxy_etf}.
    """
    # DB-first
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            mapping = db_client.get_cash_proxies()
        if mapping:
            return mapping, 'database'
    except Exception as e:
        log_portfolio_operation("cash_proxy_loader_db_failed", {"error": str(e)}, execution_time=0)

    # YAML fallback: cash_map.yaml (existing)
    try:
        import yaml
        yaml_path = _PROJECT_ROOT / "cash_map.yaml"
        if yaml_path.exists():
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            # Expect structure {USD: SGOV, EUR: ESTR, ...} OR nested with key 'cash_proxies'
            if isinstance(data, dict) and 'USD' in data or 'cash_proxies' in data:
                if 'cash_proxies' in data and isinstance(data['cash_proxies'], dict):
                    return {k: str(v) for k, v in data['cash_proxies'].items()}, 'yaml'
                else:
                    return {k: str(v) for k, v in data.items()}, 'yaml'
    except Exception as e:
        log_portfolio_operation("cash_proxy_loader_yaml_failed", {"error": str(e)}, execution_time=0)

    return {"USD": "SGOV"}, 'hardcoded'


def _deterministic_universe_hash(universe: Dict[str, List[str]]) -> str:
    items: List[Tuple[str, str]] = []
    for category, tickers in universe.items():
        for t in sorted(set(tickers)):
            items.append((category, t))
    items.sort(key=lambda x: (x[0], x[1]))
    s = json.dumps(items, separators=(",", ":"))
    return hashlib.md5(s.encode()).hexdigest()


@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def _build_factor_returns_panel_cached(
    universe_hash: str,
    start_date: str,
    end_date: str,
    total_return: bool = True,
    max_workers: int = 8,
    fmp_ticker_map_json: Optional[str] = None,
) -> pd.DataFrame:
    """
    Build aligned monthly returns panel using cached computation.

    This is the cached implementation that takes a universe hash as a cache key.
    The universe is reconstructed from the global fetch_factor_universe() function.

    Parameters
    ----------
    universe_hash : str
        Deterministic hash of the ETF universe (for caching).
    start_date, end_date : str
        Analysis window (YYYY-MM-DD).
    total_return : bool
        Prefer dividend-adjusted price series when True (fallback to close).
    max_workers : int
        ThreadPoolExecutor worker count for parallel ETF fetching.

    Returns
    -------
    pd.DataFrame
        Monthly returns panel with ETFs as columns, month-end dates as index.
        Returns are decimal (0.05 = 5% return).
        Added attributes: universe_hash, build_ms, categories, start/end dates.

    NaN handling and overlap policy
    -------------------------------
    This function intentionally does not perform a global dropna() across all
    ETFs when building the panel. The returned DataFrame preserves NaNs so that
    downstream analyses (e.g., per-category correlation matrices and overlays)
    can align only the relevant subset of series and drop NaNs at that scope.

    As a result, correlations are computed on the overlapping time periods for
    the tickers involved in each specific analysis, rather than the often much
    smaller global intersection across the entire universe.
    """
    fmp_ticker_map = json.loads(fmp_ticker_map_json) if fmp_ticker_map_json else None

    # Reconstruct universe from the cached fetch_factor_universe() function
    universe = fetch_factor_universe()

    # Verify hash matches to ensure cache consistency
    computed_hash = _deterministic_universe_hash(universe)
    if computed_hash != universe_hash:
        log_critical_alert("universe_hash_mismatch", "medium", f"Universe hash mismatch: expected {universe_hash}, got {computed_hash}", "Verify universe consistency")
        log_critical_alert("universe_hash_mismatch", "medium", "This may indicate universe changes. Proceeding with current universe.", "Monitor for data consistency issues")

    # Perform the actual computation (copied from original implementation)
    t0 = time.time()

    # Flatten universe to unique tickers and remember category per ticker
    ticker_to_category: Dict[str, str] = {}
    tickers: List[str] = []
    for cat, lst in universe.items():
        for t in lst:
            tu = str(t).upper()
            if tu not in ticker_to_category:
                ticker_to_category[tu] = cat
                tickers.append(tu)

    def _load_returns(ticker: str) -> Optional[pd.Series]:
        # Determine source category for better error reporting
        ticker_category = ticker_to_category.get(ticker, "unknown")
        source_file = _get_ticker_source_file(ticker, ticker_category)

        try:
            prices = (
                fetch_monthly_total_return_price(
                    ticker,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
                if total_return else
                fetch_monthly_close(
                    ticker,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
            )
            # LOG: Check if API returned empty data
            if prices.empty:
                log_critical_alert("factor_empty_api_data", "high", f"EMPTY API DATA: Ticker={ticker}, Category={ticker_category}, Source={source_file}, Shape={prices.shape}", "Check ticker validity and API access")
                return None
        except Exception:
            try:
                prices = fetch_monthly_close(
                    ticker,
                    start_date,
                    end_date,
                    fmp_ticker_map=fmp_ticker_map,
                )
                # LOG: Check if fallback API returned empty data
                if prices.empty:
                    log_critical_alert("factor_empty_api_data", "high", f"EMPTY FALLBACK API DATA: Ticker={ticker}, Category={ticker_category}, Source={source_file}, Shape={prices.shape}", "Check ticker validity and API access")
                    return None
            except Exception as e:
                log_critical_alert("factor_api_fetch_failed", "high", f"API FETCH FAILED: Ticker={ticker}, Category={ticker_category}, Source={source_file}, Error={str(e)}", "Check ticker validity and API access")
                return None
        try:
            rets = calc_monthly_returns(prices)
            if not isinstance(rets, pd.Series) or rets.empty:
                log_critical_alert("factor_returns_calc_empty", "medium", f"RETURNS CALCULATION EMPTY: Ticker={ticker}, Category={ticker_category}, Source={source_file}, PriceLength={len(prices)}", "Check price data quality")
                return None
            return rets
        except Exception as e:
            log_critical_alert("factor_returns_calc_failed", "medium", f"RETURNS CALCULATION FAILED: Ticker={ticker}, Category={ticker_category}, Source={source_file}, Error={str(e)}", "Check price data format")
            return None

    series_map: Dict[str, pd.Series] = {}
    failed_tickers = []

    if tickers:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_load_returns, t): t for t in tickers}
            for fut in as_completed(futures):
                tkr = futures[fut]
                ser = fut.result()
                if ser is not None and len(ser) >= 2:
                    series_map[tkr] = ser.rename(tkr)
                else:
                    failed_tickers.append(tkr)
                    ticker_category = ticker_to_category.get(tkr, "unknown")
                    source_file = _get_ticker_source_file(tkr, ticker_category)
                    log_critical_alert("factor_ticker_failed", "medium", f"TICKER FAILED: Ticker={tkr}, Category={ticker_category}, Source={source_file}, DataLength={len(ser) if ser is not None else 0}", "Check ticker validity or replace with working ticker")


    if not series_map:
        return pd.DataFrame()

    # LOG: Analyze individual ticker date ranges for the analysis period
    analysis_start = pd.to_datetime(start_date)
    analysis_end = pd.to_datetime(end_date)
    short_range_tickers = []

    for ticker, series in series_map.items():
        if not series.empty:
            ticker_start = series.index.min()
            ticker_end = series.index.max()
            ticker_category = ticker_to_category.get(ticker, "unknown")
            source_file = _get_ticker_source_file(ticker, ticker_category)

            # Use utility function for ticker coverage analysis
            from utils.ticker_validation import analyze_ticker_coverage

            coverage_analysis = analyze_ticker_coverage(
                ticker=ticker,
                ticker_start=ticker_start,
                ticker_end=ticker_end,
                analysis_start=analysis_start,
                analysis_end=analysis_end,
                category=ticker_category,
                source_file=source_file,
                start_buffer_months=6,
                end_buffer_months=6,
                high_priority_threshold_months=24
            )

            # Log issues based on analysis results
            if coverage_analysis['gap_type'] != 'sufficient':
                if coverage_analysis['is_outside_period']:
                    log_critical_alert("factor_ticker_outside_period", coverage_analysis['priority'], coverage_analysis['log_message'], coverage_analysis['recovery_action'])
                else:
                    log_critical_alert("factor_ticker_insufficient_coverage", coverage_analysis['priority'], coverage_analysis['log_message'], coverage_analysis['recovery_action'])
                short_range_tickers.append(ticker)

    # Concat and compute a diagnostic global-overlap view (for logging only)
    df_raw = pd.concat(series_map.values(), axis=1)
    overlap_df = df_raw.dropna()

    # LOG: Check for data overlap issues (diagnostic only)
    if overlap_df.empty:
        log_critical_alert("factor_no_overlap", "high", f"NO DATA OVERLAP: Raw shape={df_raw.shape}, After dropna shape={overlap_df.shape}, Successful tickers={len(series_map)}, Failed tickers={len(failed_tickers)}, Short range tickers={len(short_range_tickers)}", "Check ticker data quality and date ranges")
    elif len(overlap_df) < 12:
        log_critical_alert("factor_insufficient_overlap", "medium", f"INSUFFICIENT OVERLAP: After dropna shape={overlap_df.shape}, Overlap periods={len(overlap_df)}, Min recommended=12", "Consider adjusting date range or ticker selection")

    # Attach metadata for downstream consumers and debugging
    df_raw.attrs["universe_hash"] = universe_hash  # Use provided hash for consistency
    df_raw.attrs["build_ms"] = int((time.time() - t0) * 1000)
    df_raw.attrs["categories"] = ticker_to_category
    df_raw.attrs["start_date"] = start_date
    df_raw.attrs["end_date"] = end_date
    df_raw.attrs["total_return"] = bool(total_return)
    df_raw.attrs["cache_key"] = f"factor_returns_panel_{universe_hash}_{start_date}_{end_date}_{total_return}"
    if fmp_ticker_map:
        df_raw.attrs["fmp_ticker_map"] = fmp_ticker_map

    # Build user-friendly labels for tickers (ticker → display label) using DB-first loaders
    try:
        label_map: Dict[str, str] = {}

        # Helper: prettify UST keys like 'UST10Y' → 'UST 10Y'
        def _pretty_ust(key: str) -> str:
            s = str(key).upper().replace("UST", "UST ")
            if s.endswith(" Y"):
                s = s[:-2] + "Y"
            return s.strip()

        # Exchange proxies (market/momentum/value) → generic factor names
        try:
            exch_map = load_exchange_proxy_map()
            if isinstance(exch_map, dict):
                for _ex, ftypes in exch_map.items():
                    if not isinstance(ftypes, dict):
                        continue
                    for ftype in ("market", "momentum", "value"):
                        t = ftypes.get(ftype)
                        if t:
                            tt = str(t).upper()
                            fname = "Market" if ftype == "market" else ("Momentum" if ftype == "momentum" else "Value")
                            label_map.setdefault(tt, f"{fname} ({tt})")
        except Exception:
            pass

        # Asset-class proxies (bond/commodity/crypto)
        try:
            asset_proxies, _src = load_asset_class_proxies()
            if isinstance(asset_proxies, dict):
                for acls, proxy_map in asset_proxies.items():
                    if not isinstance(proxy_map, dict):
                        continue
                    for pkey, t in proxy_map.items():
                        if not t:
                            continue
                        tt = str(t).upper()
                        pk = str(pkey)
                        if acls == 'bond':
                            label_map.setdefault(tt, f"{_pretty_ust(pk)} ({tt})")
                        elif acls == 'commodity':
                            label_map.setdefault(tt, f"{pk.title()} ({tt})")
                        elif acls == 'crypto':
                            label_map.setdefault(tt, f"{pk.upper()} ({tt})")
                        else:
                            label_map.setdefault(tt, f"{pk.title()} ({tt})")
        except Exception:
            pass

        # Cash proxies (currency → ticker)
        try:
            cash_map, _csrc = load_cash_proxies()
            if isinstance(cash_map, dict):
                inv = {str(v).upper(): str(k).upper() for k, v in cash_map.items() if v}
                for tt, curr in inv.items():
                    label_map.setdefault(tt, f"{curr} Cash ({tt})")
        except Exception:
            pass

        # Keep only labels for tickers actually in panel; fallback to ticker itself
        present = set(df_raw.columns)
        labels_final = {t: label_map.get(t, t) for t in present}
        df_raw.attrs["labels"] = labels_final

        # Market ticker → exchange key mapping for richer labels downstream
        try:
            categories_map = df_raw.attrs.get("categories", {})
            market_tickers = {t for t, cat in categories_map.items() if cat == "market"}
            if present:
                market_exchanges: Dict[str, str] = {}
                style_exchange_map: Dict[str, Dict[str, str]] = {}

                def _extract_ticker(entry: Any) -> Optional[str]:
                    """Support plain strings or structured mappings."""
                    if isinstance(entry, dict):
                        return (
                            entry.get("ticker")
                            or entry.get("etf")
                            or entry.get("symbol")
                            or entry.get("proxy")
                        )
                    return entry

                def _extract_exchange_key(entry: Any, default_key: str) -> Optional[str]:
                    if isinstance(entry, dict):
                        return (
                            entry.get("exchange_key")
                            or entry.get("exchange")
                            or entry.get("label")
                        )
                    return default_key

                exch_map = load_exchange_proxy_map()
                if isinstance(exch_map, dict):
                    # Prefer explicit exchanges; process DEFAULT last
                    items = list(exch_map.items())
                    items.sort(key=lambda kv: (str(kv[0]).upper() == "DEFAULT", str(kv[0]).lower()))
                    for exch_key, factors in items:
                        if not isinstance(factors, dict):
                            continue
                        raw_market = factors.get("market")
                        ticker_val = _extract_ticker(raw_market)
                        resolved_key = _extract_exchange_key(raw_market, str(exch_key))
                        key_clean = str(resolved_key).strip() if resolved_key else str(exch_key).strip()
                        if not key_clean:
                            continue
                        if key_clean.upper() == "DEFAULT":
                            key_clean = "Global"
                        entry = style_exchange_map.setdefault(key_clean, {})

                        if ticker_val:
                            tt = str(ticker_val).upper()
                            if tt in present and tt not in market_exchanges:
                                market_exchanges[tt] = key_clean
                                entry.setdefault('market', tt)
                                label_map.setdefault(tt, f"{key_clean} ({tt})")

                        for ftype, raw in factors.items():
                            if ftype == 'market' or not raw:
                                continue
                            style_ticker = _extract_ticker(raw)
                            if not style_ticker:
                                continue
                            ts = str(style_ticker).upper()
                            if ts not in present:
                                continue
                            entry.setdefault(ftype, ts)
                            label_map.setdefault(ts, f"{key_clean} {ftype.title()} ({ts})")

                if market_exchanges:
                    df_raw.attrs["market_exchanges"] = market_exchanges
                    # Ensure market tickers are categorized correctly (override earlier assignments)
                    categories_map = df_raw.attrs.get("categories", {})
                    if isinstance(categories_map, dict):
                        for tt in market_exchanges:
                            categories_map[tt] = "market"

                if style_exchange_map:
                    cleaned_style = {}
                    seen_signatures = set()
                    for exch_label, mapping in style_exchange_map.items():
                        if not isinstance(mapping, dict):
                            continue
                        market_raw = mapping.get('market')
                        if not market_raw:
                            continue
                        unique_tickers = [str(v).upper() for v in mapping.values() if v]
                        if len(set(unique_tickers)) < 2:
                            continue
                        market_ticker = str(market_raw).upper()
                        others = tuple(sorted(str(mapping[k]).upper() for k in mapping if k != 'market' and mapping.get(k)))
                        signature = (market_ticker, others)
                        if signature in seen_signatures:
                            continue
                        seen_signatures.add(signature)
                        cleaned_style[exch_label] = mapping
                    if cleaned_style:
                        df_raw.attrs["style_exchanges"] = cleaned_style

        except Exception:
            pass
    except Exception:
        # Labels are optional; ignore failures
        df_raw.attrs["labels"] = {t: t for t in df_raw.columns}

    # Return panel with NaNs retained; downstream steps will align and drop per scope
    return df_raw


@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def fetch_factor_universe(use_database: bool = True) -> Dict[str, List[str]]:
    """
    Build the factor ETF universe categorized by factor/asset classes.

    Called by:
    - ``services.factor_intelligence_service.FactorIntelligenceService``.

    Calls into:
    - DB-first proxy loaders (industry/exchange/asset/cash), with YAML/hardcoded
      fallbacks in loader functions.

    Returns
    -------
    Dict[str, List[str]]
        {
          'industry': [...],
          'style':    [...],  # momentum/value ETFs
          'market':   [...],  # market proxies
          'bond':     [...],
          'commodity': [...],
          'crypto':    [...]
        }
    """
    # Industry proxies (DB‑first via proxy_builder loader)
    industry_map = load_industry_etf_map()
    industry_set = set()
    if isinstance(industry_map, dict):
        for entry in industry_map.values():
            if isinstance(entry, dict):
                etf = entry.get("etf")
                if etf:
                    industry_set.add(str(etf))
            elif entry:
                industry_set.add(str(entry))
    industry_etfs = sorted(industry_set)

    # Exchange proxies (DB‑first)
    exch_map = load_exchange_proxy_map()
    style_set, market_set = set(), set()
    if isinstance(exch_map, dict):
        for exch, factors in exch_map.items():
            if not isinstance(factors, dict):
                continue
            # market
            mkt = factors.get('market')
            if mkt:
                market_set.add(str(mkt))
            # style
            mom = factors.get('momentum')
            val = factors.get('value')
            if mom:
                style_set.add(str(mom))
            if val:
                style_set.add(str(val))

    # Asset class proxies
    asset_proxies, _src = load_asset_class_proxies()
    bond_etfs = sorted(set(asset_proxies.get('bond', {}).values()))
    commodity_etfs = sorted(set(asset_proxies.get('commodity', {}).values()))
    crypto_etfs = sorted(set(asset_proxies.get('crypto', {}).values()))

    # Cash proxies (DB-first): include in universe for macro composites
    cash_map, _cash_src = load_cash_proxies()
    cash_etfs = sorted(set(str(v).upper() for v in cash_map.values())) if isinstance(cash_map, dict) else []

    universe: Dict[str, List[str]] = {
        'industry': industry_etfs,
        'style':    sorted(style_set),
        'market':   sorted(market_set),
        'bond':      bond_etfs,
        'commodity': commodity_etfs,
        'crypto':    crypto_etfs,
        'cash':      cash_etfs,
    }

    # Remove empties for cleanliness
    universe = {k: v for k, v in universe.items() if v}
    return universe


def build_factor_returns_panel(
    universe: Dict[str, List[str]],
    start_date: str,
    end_date: str,
    total_return: bool = True,
    max_workers: int = 8,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Build aligned monthly returns panel for the provided ETF universe.

    This is the public API function that maintains backward compatibility.
    It computes a hash of the universe and delegates to the cached implementation.

    Called by:
    - ``FactorIntelligenceService._panel`` as the main returns-panel boundary.

    Parameters
    ----------
    universe : Dict[str, List[str]]
        Mapping of category → list of ETF tickers.
    start_date, end_date : str
        Analysis window (YYYY-MM-DD).
    total_return : bool
        Prefer dividend-adjusted price series when True (fallback to close).
    max_workers : int
        ThreadPoolExecutor worker count for parallel ETF fetching.

    Returns
    -------
    pd.DataFrame
        Monthly returns panel with ETFs as columns, month-end dates as index.
        Returns are decimal (0.05 = 5% return).
        Added attributes: universe_hash, build_ms, categories, start/end dates.
    """
    # Compute deterministic hash for caching
    universe_hash = _deterministic_universe_hash(universe)

    fmp_ticker_map_json = json.dumps(fmp_ticker_map, sort_keys=True) if fmp_ticker_map else None

    # Delegate to the cached implementation
    return _build_factor_returns_panel_cached(
        universe_hash,
        start_date,
        end_date,
        total_return,
        max_workers,
        fmp_ticker_map_json,
    )


def _equal_weight(series_list: List[pd.Series]) -> Optional[pd.Series]:
    if not series_list:
        return None
    df = pd.concat(series_list, axis=1).dropna()
    if df.empty:
        return None
    return df.mean(axis=1)


def _build_industry_series_by_granularity(
    returns_panel: pd.DataFrame,
    granularity: str = 'industry'
) -> Tuple[Dict[str, pd.Series], Dict[str, Any]]:
    """
    Construct label → returns series for industry category according to requested granularity.

    granularity:
      - 'industry': one series per industry (using its ETF proxy)
      - 'group':    composites per sector_group (equal-weight of member industry ETFs),
                    with industries lacking a sector_group kept as individual entries
    """
    info: Dict[str, Any] = {"granularity": granularity}

    # Reverse mapping: industry -> ETF
    industry_map = load_industry_etf_map()
    if not isinstance(industry_map, dict):
        return {}, {**info, "error": "industry_map_unavailable"}

    # Build returns per industry label (only if ETF exists in the panel)
    label_to_series: Dict[str, pd.Series] = {}
    etf_to_series: Dict[str, pd.Series] = {t: returns_panel[t] for t in returns_panel.columns}

    # Sector groups from DB (industry -> group)
    groups_map = load_industry_buckets() if granularity == 'group' else {}

    if granularity == 'industry':
        used = 0
        for industry, etf in industry_map.items():
            etf_u = str(etf).upper()
            if etf_u in etf_to_series:
                label_to_series[industry] = etf_to_series[etf_u]
                used += 1
        info.update({"industries_total": len(industry_map), "industries_used": used})
        return label_to_series, info

    # granularity == 'group'
    # Compose composites per group
    group_members: Dict[str, List[str]] = {}
    for industry, group in groups_map.items():
        if not group:
            continue
        etf = industry_map.get(industry)
        if not etf:
            continue
        etf_u = str(etf).upper()
        if etf_u not in etf_to_series:
            continue
        group_members.setdefault(group, [])
        # Avoid duplicates of the same ETF within a group
        if etf_u not in group_members[group]:
            group_members[group].append(etf_u)

    group_sizes = {g: len(tks) for g, tks in group_members.items()}
    composites_built = 0
    for group, tks in group_members.items():
        ser_list = [etf_to_series[t] for t in tks if t in etf_to_series]
        comp = _equal_weight(ser_list)
        if comp is not None:
            comp.name = group
            label_to_series[group] = comp
            composites_built += 1

    # Industries without a sector_group → keep individually
    ungrouped: List[str] = []
    for industry, etf in industry_map.items():
        if groups_map.get(industry):
            continue  # already included via group composite
        etf_u = str(etf).upper()
        if etf_u in etf_to_series:
            if granularity != 'group':
                label_to_series[industry] = etf_to_series[etf_u]
            else:
                ungrouped.append(industry)

    info.update({
        "groups_total": len(group_members),
        "group_sizes": group_sizes,
        "group_composites_built": composites_built,
        "unlabeled_industries": len(ungrouped),
        "unlabeled_industry_labels": ungrouped if granularity == 'group' else None,
    })
    return label_to_series, info


def compute_per_category_correlation_matrices(
    returns_panel: pd.DataFrame,
    industry_granularity: str = 'industry',
    include_categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute correlation matrices per category with optional industry granularity control.

    Returns
    -------
    dict with keys:
      - matrices: {category: pd.DataFrame}
      - data_quality: {category: {...}}
      - performance: timing information (ms)
      - analysis_metadata: echo of panel attrs
    """
    t0 = time.time()
    categories = returns_panel.attrs.get("categories", {})
    uniq_categories = sorted(set(categories.values()))
    wanted = include_categories or uniq_categories

    matrices: Dict[str, pd.DataFrame] = {}
    dq: Dict[str, Any] = {}
    per_cat_ms: Dict[str, int] = {}
    labels_map = returns_panel.attrs.get("labels", {}) if hasattr(returns_panel, 'attrs') else {}

    def _apply_labels(df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame):
            return df
        if isinstance(labels_map, dict) and labels_map:
            df = df.rename(
                index=lambda x: labels_map.get(str(x), str(x)),
                columns=lambda x: labels_map.get(str(x), str(x))
            )
        return df

    for cat in wanted:
        c0 = time.time()
        if cat == 'industry':
            # When granularity="group", emit both aggregate groups and raw industries
            modes = [('industry', 'industry')]
            if (industry_granularity or '').lower() == 'group':
                modes.insert(0, ('industry_groups', 'group'))

            for out_key, gran in modes:
                c0_mode = time.time()
                label_series, info = _build_industry_series_by_granularity(returns_panel, granularity=gran)
                if not label_series:
                    dq[out_key] = {**info, "status": "skipped", "reason": "no_series"}
                    per_cat_ms[out_key] = int((time.time() - c0_mode) * 1000)
                    continue
                df = pd.concat(label_series.values(), axis=1)
                df.columns = list(label_series.keys())
                df = df.dropna()
                if df.shape[1] < 2:
                    dq[out_key] = {**info, "status": "skipped", "reason": "insufficient_labels", "labels": df.columns.tolist()}
                    per_cat_ms[out_key] = int((time.time() - c0_mode) * 1000)
                    continue
                matrices[out_key] = _apply_labels(df.corr())
                dq[out_key] = {**info, "status": "ok", "labels": df.columns.tolist(), "observations": int(df.shape[0])}
                per_cat_ms[out_key] = int((time.time() - c0_mode) * 1000)

            # Skip default processing since we handled industry separately
            continue

        if cat == 'style':
            tickers = [t for t, k in categories.items() if k == cat]
            if len(tickers) < 2:
                dq[cat] = {"status": "skipped", "reason": "insufficient_tickers", "tickers": tickers}
                per_cat_ms[cat] = int((time.time() - c0) * 1000)
            else:
                df = returns_panel.reindex(columns=tickers).dropna()
                if df.shape[1] < 2 or df.empty:
                    dq[cat] = {"status": "skipped", "reason": "no_overlap", "tickers": tickers}
                    per_cat_ms[cat] = int((time.time() - c0) * 1000)
                else:
                    matrices[cat] = _apply_labels(df.corr())
                    dq[cat] = {"status": "ok", "tickers_used": df.columns.tolist(), "observations": int(df.shape[0])}
                    per_cat_ms[cat] = int((time.time() - c0) * 1000)

            style_exchanges = returns_panel.attrs.get("style_exchanges")
            if isinstance(style_exchanges, dict) and style_exchanges:
                for exch_name in sorted(style_exchanges.keys(), key=str):
                    entry = style_exchanges.get(exch_name) or {}
                    ordered: List[str] = []
                    seen: set = set()
                    if isinstance(entry, dict):
                        keys = ['market'] + sorted(k for k in entry.keys() if k != 'market')
                        for kf in keys:
                            tk = entry.get(kf)
                            if not tk:
                                continue
                            tk_u = str(tk).upper()
                            if tk_u in returns_panel.columns and tk_u not in seen:
                                ordered.append(tk_u)
                                seen.add(tk_u)

                    key_name = f"style:{exch_name}"
                    c0_ex = time.time()
                    if len(ordered) < 2:
                        dq[key_name] = {"status": "skipped", "reason": "insufficient_tickers", "tickers": ordered}
                        per_cat_ms[key_name] = int((time.time() - c0_ex) * 1000)
                        continue
                    df_ex = returns_panel.reindex(columns=ordered).dropna()
                    if df_ex.shape[1] < 2 or df_ex.empty:
                        dq[key_name] = {"status": "skipped", "reason": "no_overlap", "tickers": ordered}
                        per_cat_ms[key_name] = int((time.time() - c0_ex) * 1000)
                        continue
                    matrices[key_name] = _apply_labels(df_ex.corr())
                    dq[key_name] = {
                        "status": "ok",
                        "tickers_used": df_ex.columns.tolist(),
                        "observations": int(df_ex.shape[0]),
                        "factors": {k: entry.get(k) for k in sorted(entry.keys())},
                    }
                    per_cat_ms[key_name] = int((time.time() - c0_ex) * 1000)

            continue

        # Other categories: filter by panel attrs
        tickers = [t for t, k in categories.items() if k == cat]
        if len(tickers) < 2:
            dq[cat] = {"status": "skipped", "reason": "insufficient_tickers", "tickers": tickers}
            per_cat_ms[cat] = int((time.time() - c0) * 1000)
            continue
        df = returns_panel.reindex(columns=tickers).dropna()
        if df.shape[1] < 2 or df.empty:
            dq[cat] = {"status": "skipped", "reason": "no_overlap", "tickers": tickers}
            per_cat_ms[cat] = int((time.time() - c0) * 1000)
            continue
        matrices[cat] = _apply_labels(df.corr())
        dq[cat] = {"status": "ok", "tickers_used": df.columns.tolist(), "observations": int(df.shape[0])}
        per_cat_ms[cat] = int((time.time() - c0) * 1000)

    out = {
        "matrices": matrices,
        "data_quality": dq,
        "performance": {
            "per_category_corr_ms": per_cat_ms,
            "total_corr_ms": int((time.time() - t0) * 1000),
        },
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "total_return": returns_panel.attrs.get("total_return", True),
        },
    }

    market_exchanges = returns_panel.attrs.get("market_exchanges") if hasattr(returns_panel, 'attrs') else None
    if isinstance(market_exchanges, dict) and 'market' in matrices:
        market_df = matrices['market']
        rename_map = {}
        for tkr, exch in market_exchanges.items():
            if not exch:
                continue
            pretty = str(exch).replace('_', ' ').strip().title()
            new_label = f"{pretty} ({tkr})"
            current_label = labels_map.get(str(tkr), str(tkr)) if isinstance(labels_map, dict) else str(tkr)
            rename_map[current_label] = new_label
        if rename_map:
            matrices['market'] = market_df.rename(index=rename_map, columns=rename_map)

    return out

def _calculate_group_rate_betas(
    returns_panel: pd.DataFrame,
    dy: pd.DataFrame,
    used_maturities: List[str]
) -> Dict[str, Dict[str, float]]:
    """
    Calculate rate betas for industry groups using equal-weighted composites.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Monthly returns panel with category information
    dy : pd.DataFrame
        Treasury yield changes (Δy) for rate factors
    used_maturities : List[str]
        Rate factor keys to calculate betas for

    Returns
    -------
    Dict[str, Dict[str, float]]
        Group betas: {group_name: {rate_key: beta_value}}
    """
    try:
        # Build group composites using same logic as correlation calculation
        label_series, _ = _build_industry_series_by_granularity(returns_panel, granularity='group')

        if not label_series:
            return {}

        group_betas = {}
        from factor_utils import compute_multifactor_betas

        for group_name, group_series in label_series.items():
            aligned = pd.concat([group_series, dy[used_maturities]], axis=1).dropna()
            if aligned.shape[0] < 2:
                continue

            group_betas[group_name] = {}
            for rate_key in used_maturities:
                try:
                    result = compute_multifactor_betas(
                        aligned.iloc[:, 0],  # group composite returns
                        aligned[[rate_key]]  # single rate factor
                    )
                    coefficient = result.get('betas', {}).get(rate_key, 0.0)
                    group_betas[group_name][rate_key] = float(coefficient)
                except Exception:
                    group_betas[group_name][rate_key] = 0.0

        return group_betas

    except Exception:
        # Graceful fallback if group calculation fails
        return {}


def compute_rate_sensitivity(
    returns_panel: pd.DataFrame,
    maturities: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Estimate rate betas via OLS regressions between ETF returns and Treasury Δy.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Monthly returns panel with attrs populated by build_factor_returns_panel().
    maturities : Optional[List[str]]
        Desired rate factor keys (e.g., ["UST2Y","UST5Y"]). Defaults to settings.
    categories : Optional[List[str]]
        Subset of categories to include (default: ['bond','industry','market']).

    Returns
    -------
    dict with keys:
      - matrix: pd.DataFrame (index=tickers, columns=rate factors)
      - data_quality: {used_maturities, available_maturities, per_ticker_obs}
      - performance: {rate_sensitivity_ms}
      - analysis_metadata: echo of panel attrs
    """
    t0 = time.time()
    cats = returns_panel.attrs.get("categories", {})
    all_tickers = list(returns_panel.columns)

    default_cats = FACTOR_INTELLIGENCE_DEFAULTS.get("default_categories", {}).get("rate_sensitivity", ["bond", "industry", "market"])
    included_cats = categories or default_cats
    chosen = [t for t in all_tickers if cats.get(t) in included_cats]

    # Load monthly yield levels and convert to Δy in decimal
    from factor_utils import fetch_monthly_treasury_yield_levels, prepare_rate_factors
    yl = fetch_monthly_treasury_yield_levels(
        start_date=returns_panel.attrs.get("start_date"),
        end_date=returns_panel.attrs.get("end_date"),
    )
    rate_keys = maturities or RATE_FACTOR_CONFIG.get("default_maturities", ["UST2Y", "UST5Y", "UST10Y", "UST30Y"])
    dy = prepare_rate_factors(yl, keys=rate_keys)

    # Compute regression betas per ticker
    beta_rows: Dict[str, Dict[str, float]] = {}
    per_ticker_obs: Dict[str, int] = {}
    per_ticker_r2: Dict[str, float] = {}
    used_maturities: List[str] = [c for c in dy.columns if c in rate_keys]

    from factor_utils import compute_multifactor_betas
    from utils.sector_config import resolve_sector_preferences

    core_tickers, preferred_labels = resolve_sector_preferences()

    for t in chosen:
        aligned = pd.concat([returns_panel[t], dy[used_maturities]], axis=1).dropna()
        per_ticker_obs[t] = int(aligned.shape[0])
        if aligned.shape[0] < 2:
            continue
        res = compute_multifactor_betas(aligned.iloc[:, 0], aligned.iloc[:, 1:])
        betas = res.get('betas', {}) or {}
        per_ticker_r2[t] = float(res.get('r2_adj') or res.get('r2') or 0.0)
        beta_rows[t] = {rk: float(betas.get(rk, float('nan'))) for rk in used_maturities}

    matrix = pd.DataFrame.from_dict(beta_rows, orient='index').reindex(columns=used_maturities)

    result = {
        "matrix": matrix,
        "data_quality": {
            "available_maturities": list(dy.columns),
            "used_maturities": used_maturities,
            "per_ticker_obs": per_ticker_obs,
            "per_ticker_r2": per_ticker_r2,
            "included_categories": included_cats,
        },
        "performance": {
            "rate_sensitivity_ms": int((time.time() - t0) * 1000)
        },
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "preferred_tickers": core_tickers,
            "preferred_labels": preferred_labels,
        },
    }

    # Add industry group rate betas if industry category is included
    if 'industry' in included_cats:
        group_betas = _calculate_group_rate_betas(returns_panel, dy, used_maturities)
        if group_betas:
            group_matrix = pd.DataFrame.from_dict(group_betas, orient='index').reindex(columns=used_maturities)
            result['industry_groups'] = {
                'matrix': group_matrix,
                'analysis_metadata': {
                    'preferred_tickers': list(group_betas.keys()),
                    'preferred_labels': {k: k for k in group_betas.keys()}
                }
            }

    return result


def _calculate_group_market_betas(
    returns_panel: pd.DataFrame,
    bench_df: pd.DataFrame,
    benchmarks_used: List[str]
) -> Dict[str, Dict[str, float]]:
    """
    Calculate market betas for industry groups using equal-weighted composites.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Monthly returns panel with category information
    bench_df : pd.DataFrame
        Benchmark returns data
    benchmarks_used : List[str]
        List of benchmark tickers to calculate betas against

    Returns
    -------
    Dict[str, Dict[str, float]]
        Group betas: {group_name: {benchmark_key: beta_value}}
    """
    try:
        # Build group composites using same logic as correlation calculation
        label_series, _ = _build_industry_series_by_granularity(returns_panel, granularity='group')

        if not label_series:
            return {}

        group_betas = {}
        from factor_utils import compute_multifactor_betas

        for group_name, group_series in label_series.items():
            aligned = pd.concat([group_series, bench_df], axis=1).dropna()
            if aligned.shape[0] < 2:
                continue

            group_betas[group_name] = {}
            for benchmark in benchmarks_used:
                try:
                    result = compute_multifactor_betas(
                        aligned.iloc[:, 0],  # group composite returns
                        aligned[[benchmark]]  # single benchmark
                    )
                    coefficient = result.get('betas', {}).get(benchmark, 0.0)
                    group_betas[group_name][benchmark] = float(coefficient)
                except Exception:
                    group_betas[group_name][benchmark] = 0.0

        return group_betas

    except Exception:
        # Graceful fallback if group calculation fails
        return {}


def compute_market_sensitivity(
    returns_panel: pd.DataFrame,
    benchmarks: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute correlation between ETF returns and market benchmark returns.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Monthly returns panel with attrs populated by build_factor_returns_panel().
    benchmarks : Optional[List[str]]
        List of benchmark tickers (default: ["SPY"]).
    categories : Optional[List[str]]
        Subset of categories to include (default: ['industry','style']).

    Returns
    -------
    dict with keys:
      - matrix: pd.DataFrame (index=tickers, columns=benchmarks)
      - data_quality: {benchmarks_used, per_ticker_obs}
      - performance: {market_sensitivity_ms}
      - analysis_metadata: echo of panel attrs
    """
    t0 = time.time()
    cats = returns_panel.attrs.get("categories", {})
    fmp_ticker_map = returns_panel.attrs.get("fmp_ticker_map")
    all_tickers = list(returns_panel.columns)

    default_cats = FACTOR_INTELLIGENCE_DEFAULTS.get("default_categories", {}).get("market_sensitivity", ["industry", "style"])
    included_cats = categories or default_cats
    chosen = [t for t in all_tickers if cats.get(t) in included_cats]

    bench_list = benchmarks or ["SPY"]

    # Build benchmark returns
    bench_series: Dict[str, pd.Series] = {}
    for b in bench_list:
        bu = str(b).upper()
        if bu in returns_panel.columns:
            bench_series[bu] = returns_panel[bu]
            continue
        # fetch
        try:
            prices = fetch_monthly_total_return_price(
                bu,
                returns_panel.attrs.get("start_date"),
                returns_panel.attrs.get("end_date"),
                fmp_ticker_map=fmp_ticker_map,
            )
        except Exception:
            prices = fetch_monthly_close(
                bu,
                returns_panel.attrs.get("start_date"),
                returns_panel.attrs.get("end_date"),
                fmp_ticker_map=fmp_ticker_map,
            )
        try:
            bench_series[bu] = calc_monthly_returns(prices).rename(bu)
        except Exception:
            # skip if can't compute
            continue

    if not bench_series:
        return {
            "matrix": pd.DataFrame(),
            "data_quality": {"benchmarks_used": [], "error": "no_benchmarks_available"},
            "performance": {"market_sensitivity_ms": int((time.time() - t0) * 1000)},
            "analysis_metadata": {
                "start_date": returns_panel.attrs.get("start_date"),
                "end_date": returns_panel.attrs.get("end_date"),
                "universe_hash": returns_panel.attrs.get("universe_hash"),
            },
        }

    bench_df = pd.concat(bench_series.values(), axis=1).dropna()
    benchmarks_used = list(bench_df.columns)

    beta_rows: Dict[str, Dict[str, float]] = {}
    per_ticker_obs: Dict[str, int] = {}
    per_ticker_r2: Dict[str, float] = {}
    from factor_utils import compute_multifactor_betas
    from utils.sector_config import resolve_sector_preferences

    core_tickers, preferred_labels = resolve_sector_preferences()

    for t in chosen:
        if t in benchmarks_used:
            continue
        aligned = pd.concat([returns_panel[t], bench_df], axis=1).dropna()
        per_ticker_obs[t] = int(aligned.shape[0])
        if aligned.shape[0] < 2:
            continue
        res = compute_multifactor_betas(aligned.iloc[:, 0], aligned.iloc[:, 1:])
        betas = res.get('betas', {}) or {}
        per_ticker_r2[t] = float(res.get('r2_adj') or res.get('r2') or 0.0)
        beta_rows[t] = {b: float(betas.get(b, float('nan'))) for b in benchmarks_used}

    matrix = pd.DataFrame.from_dict(beta_rows, orient='index').reindex(columns=benchmarks_used)

    result = {
        "matrix": matrix,
        "data_quality": {
            "benchmarks_used": benchmarks_used,
            "per_ticker_obs": per_ticker_obs,
            "per_ticker_r2": per_ticker_r2,
            "included_categories": included_cats,
        },
        "performance": {
            "market_sensitivity_ms": int((time.time() - t0) * 1000)
        },
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "preferred_tickers": core_tickers,
            "preferred_labels": preferred_labels,
        },
    }

    # Add industry group market betas if industry category is included
    if 'industry' in included_cats:
        group_betas = _calculate_group_market_betas(returns_panel, bench_df, benchmarks_used)
        if group_betas:
            group_matrix = pd.DataFrame.from_dict(group_betas, orient='index').reindex(columns=benchmarks_used)
            result['industry_groups'] = {
                'matrix': group_matrix,
                'analysis_metadata': {
                    'preferred_tickers': list(group_betas.keys()),
                    'preferred_labels': {k: k for k in group_betas.keys()}
                }
            }

    return result


def _perf_pick_fields(perf: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a compact, consistent set of performance fields from the
    calculate_portfolio_performance_metrics() result.
    """
    if not isinstance(perf, dict) or 'returns' not in perf:
        return {"error": perf.get("error", "unknown_error") if isinstance(perf, dict) else "invalid_result"}
    out = {
        "annual_return": perf["returns"].get("annualized_return"),
        "volatility": perf["risk_metrics"].get("volatility"),
        "sharpe_ratio": perf["risk_adjusted_returns"].get("sharpe_ratio"),
        "max_drawdown": perf["risk_metrics"].get("maximum_drawdown"),
        "beta_to_market": perf.get("benchmark_analysis", {}).get("beta"),
    }
    dy = perf.get("dividend_metrics", {}).get("portfolio_dividend_yield")
    if dy is not None:
        out["dividend_yield"] = dy
    return out


def compute_factor_performance_profiles(
    returns_panel: pd.DataFrame,
    benchmark_ticker: str = "SPY",
) -> Dict[str, Any]:
    """
    Compute per-ETF performance profiles using the existing performance engine.

    Returns a dict with profiles keyed by ticker and timing/metadata blocks.
    """
    t0 = time.time()
    start = returns_panel.attrs.get("start_date")
    end = returns_panel.attrs.get("end_date")

    profiles: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}

    for t in returns_panel.columns:
        weights = {t: 1.0}
        try:
            perf = calculate_portfolio_performance_metrics(weights, start, end, benchmark_ticker=benchmark_ticker)
            profiles[t] = _perf_pick_fields(perf)
        except Exception as e:
            errors[t] = str(e)

    result = {
        "profiles": profiles,
        "data_quality": {
            "tickers_analyzed": len(profiles),
            "tickers_failed": list(errors.keys()),
        },
        "performance": {
            "factor_performance_ms": int((time.time() - t0) * 1000)
        },
        "analysis_metadata": {
            "start_date": start,
            "end_date": end,
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "benchmark_ticker": benchmark_ticker,
        },
    }
    return result


def compute_composite_performance(
    returns_panel: pd.DataFrame,
    include_macro: bool = True,
    include_factor_categories: bool = True,
    composite_weighting: str = "equal",
    benchmark_ticker: str = "SPY",
) -> Dict[str, Any]:
    """
    Compute composite performance for macro groups and factor categories.

    - Macro composites:
        equity (market+industry+style), fixed_income (bond), cash (cash), commodity, crypto
    - Factor categories:
        industry, style, market, bond, commodity, crypto
    """
    t0 = time.time()
    start = returns_panel.attrs.get("start_date")
    end = returns_panel.attrs.get("end_date")
    cats = returns_panel.attrs.get("categories", {})

    def _weights_for_tickers(tks: List[str]) -> Dict[str, float]:
        if not tks:
            return {}
        w = 1.0 / len(tks)
        return {t: w for t in tks}

    # Build macro groups from categories available in the panel
    tickers_by_cat: Dict[str, List[str]] = {}
    for t, c in cats.items():
        tickers_by_cat.setdefault(c, []).append(t)

    macro_defs = {
        "equity": tickers_by_cat.get("market", []) + tickers_by_cat.get("industry", []) + tickers_by_cat.get("style", []),
        "fixed_income": tickers_by_cat.get("bond", []),
        "cash": tickers_by_cat.get("cash", []),
        "commodity": tickers_by_cat.get("commodity", []),
        "crypto": tickers_by_cat.get("crypto", []),
    }

    macro_perf: Dict[str, Dict[str, Any]] = {}
    if include_macro:
        for name, tks in macro_defs.items():
            if len(tks) < 1:
                continue
            try:
                perf = calculate_portfolio_performance_metrics(_weights_for_tickers(tks), start, end, benchmark_ticker=benchmark_ticker)
                macro_perf[name] = _perf_pick_fields(perf)
            except Exception:
                continue

    # Factor category composites
    category_perf: Dict[str, Dict[str, Any]] = {}
    if include_factor_categories:
        for cat_name, tks in tickers_by_cat.items():
            if len(tks) < 1:
                continue
            try:
                perf = calculate_portfolio_performance_metrics(_weights_for_tickers(tks), start, end, benchmark_ticker=benchmark_ticker)
                category_perf[cat_name] = _perf_pick_fields(perf)
            except Exception:
                continue

    result = {
        "macro_composites": macro_perf,
        "factor_category_composites": category_perf,
        "data_quality": {
            "macro_coverage": {k: len(v) if isinstance(v, dict) else 0 for k, v in macro_defs.items()},
            "categories_present": {k: len(v) for k, v in tickers_by_cat.items()},
        },
        "performance": {"composite_performance_ms": int((time.time() - t0) * 1000)},
        "analysis_metadata": {
            "start_date": start,
            "end_date": end,
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "benchmark_ticker": benchmark_ticker,
        },
    }
    return result


def parse_windows(
    windows: Optional[List[str]],
    end_date: Optional[str] = None,
    invalid_windows: Optional[List[str]] = None,
) -> List[Tuple[str, int]]:
    """
    Parse window tokens to (label, month_count) tuples.

    Valid windows: 1m, 3m, 6m, 1y, 2y, ytd (case-insensitive).
    Invalid windows are skipped and optionally appended to invalid_windows.
    """
    defaults = (
        FACTOR_INTELLIGENCE_DEFAULTS.get("returns", {}).get("default_windows")
        or ["1m", "3m", "6m", "1y"]
    )
    if windows is None:
        requested = list(defaults)
    elif isinstance(windows, (list, tuple, set)):
        requested = list(windows)
    else:
        requested = [str(windows)]

    month_map = {
        "1m": 1,
        "3m": 3,
        "6m": 6,
        "1y": 12,
        "2y": 24,
    }
    parsed: List[Tuple[str, int]] = []
    seen: set[str] = set()
    bad: List[str] = []

    for raw in requested:
        token = str(raw).strip().lower()
        if not token:
            bad.append(str(raw))
            continue
        if token in seen:
            continue
        seen.add(token)

        if token in month_map:
            parsed.append((token, month_map[token]))
            continue
        if token == "ytd":
            try:
                end_ts = pd.Timestamp(end_date) if end_date else pd.Timestamp.utcnow()
                months = max(int(end_ts.month), 1)
            except Exception:
                months = 1
            parsed.append((token, months))
            continue

        bad.append(str(raw))
        log_portfolio_operation(
            "factor_returns_invalid_window",
            {
                "window": str(raw),
                "valid_windows": ["1m", "3m", "6m", "1y", "2y", "ytd"],
            },
            execution_time=0,
        )

    if invalid_windows is not None and bad:
        invalid_windows.extend(bad)

    if not parsed:
        raise ValueError("No valid windows specified")
    return parsed


def compute_factor_returns_snapshot(
    returns_panel: pd.DataFrame,
    windows=None,
    categories: Optional[List[str]] = None,
    industry_granularity: str = "group",
) -> Dict[str, Any]:
    """
    Compute lightweight multi-window factor returns snapshot.

    Parameters
    ----------
    windows : list of str or list of (str, int) tuples
        Either raw window tokens (e.g., ["1m", "3m"]) or pre-parsed
        (label, month_count) tuples from parse_windows().

    Returns
    -------
    dict
        {
          "factors": {ticker: {...}},
          "industry_groups": {group_label: {...}},
          "rankings": {window: [...]},
          "by_category": {category: {window: {...}}},
          "windows": [...],
          "data_quality": {...},
          "performance": {...},
          "analysis_metadata": {...},
        }
    """
    t0 = time.time()

    invalid_windows: List[str] = []
    # Accept pre-parsed windows (list of tuples) or raw strings
    if windows and isinstance(windows[0], tuple):
        parsed_windows = windows
    else:
        parsed_windows = parse_windows(
            windows,
            end_date=returns_panel.attrs.get("end_date"),
            invalid_windows=invalid_windows,
        )
    window_labels = [w for w, _ in parsed_windows]

    category_map = returns_panel.attrs.get("categories", {}) or {}
    labels_map = returns_panel.attrs.get("labels", {}) if hasattr(returns_panel, "attrs") else {}
    categories_filter = {str(c).lower() for c in categories} if categories else None

    chosen_tickers: List[str] = []
    for ticker in returns_panel.columns:
        cat = str(category_map.get(ticker, "unknown")).lower()
        if categories_filter and cat not in categories_filter:
            continue
        chosen_tickers.append(ticker)

    factors: Dict[str, Any] = {}
    rankings: Dict[str, List[Dict[str, Any]]] = {w: [] for w in window_labels}
    by_category_raw: Dict[str, Dict[str, List[Tuple[str, str, float]]]] = {}

    def _window_metrics(series: pd.Series, month_count: int) -> Optional[Dict[str, Any]]:
        tail = series.dropna().tail(month_count)
        if tail.empty:
            return None
        obs = int(tail.shape[0])
        total_return = float(np.prod(1.0 + tail.values) - 1.0)
        out: Dict[str, Any] = {
            "total_return": round(total_return, 8),
            "observations": obs,
        }
        if obs >= 3:
            try:
                annualized = (1.0 + total_return) ** (12.0 / obs) - 1.0
            except Exception:
                annualized = None
            vol = float(tail.std(ddof=1) * np.sqrt(12.0)) if obs > 1 else None
            if annualized is not None and np.isfinite(annualized):
                out["annualized_return"] = round(float(annualized), 8)
            if vol is not None and np.isfinite(vol):
                out["volatility"] = round(float(vol), 8)
        return out

    for ticker in chosen_tickers:
        series = returns_panel[ticker].dropna()
        if series.empty:
            continue
        category = str(category_map.get(ticker, "unknown")).lower()
        label = labels_map.get(ticker, ticker) if isinstance(labels_map, dict) else ticker
        factor_entry: Dict[str, Any] = {
            "ticker": ticker,
            "label": label,
            "category": category,
            "windows": {},
        }

        for window_label, month_count in parsed_windows:
            metrics = _window_metrics(series, month_count)
            if metrics is None:
                continue
            factor_entry["windows"][window_label] = metrics
            total_return = float(metrics.get("total_return", 0.0))
            rankings.setdefault(window_label, []).append({
                "ticker": ticker,
                "label": label,
                "category": category,
                "total_return": round(total_return, 8),
                "observations": metrics.get("observations"),
            })
            by_category_raw.setdefault(category, {}).setdefault(window_label, []).append(
                (ticker, label, total_return)
            )

        if factor_entry["windows"]:
            factors[ticker] = factor_entry

    for window_label, rows in rankings.items():
        rankings[window_label] = sorted(
            rows,
            key=lambda item: float(item.get("total_return", 0.0)),
            reverse=True,
        )

    by_category: Dict[str, Dict[str, Any]] = {}
    for category, per_window in by_category_raw.items():
        by_category[category] = {}
        for window_label, rows in per_window.items():
            if not rows:
                continue
            ordered = sorted(rows, key=lambda r: r[2], reverse=True)
            avg_return = float(np.mean([r[2] for r in rows]))
            best = ordered[0]
            worst = ordered[-1]
            by_category[category][window_label] = {
                "avg_return": round(avg_return, 8),
                "count": len(rows),
                "best": {
                    "ticker": best[0],
                    "label": best[1],
                    "total_return": round(float(best[2]), 8),
                },
                "worst": {
                    "ticker": worst[0],
                    "label": worst[1],
                    "total_return": round(float(worst[2]), 8),
                },
            }

    industry_groups: Dict[str, Any] = {}
    industry_info: Dict[str, Any] = {}
    if (
        (industry_granularity or "").lower() == "group"
        and (categories_filter is None or "industry" in categories_filter)
    ):
        group_series, industry_info = _build_industry_series_by_granularity(
            returns_panel,
            granularity="group",
        )
        group_sizes = industry_info.get("group_sizes", {}) if isinstance(industry_info, dict) else {}
        for group_label, series in group_series.items():
            group_entry: Dict[str, Any] = {
                "members": group_sizes.get(group_label),
                "windows": {},
            }
            for window_label, month_count in parsed_windows:
                metrics = _window_metrics(series, month_count)
                if metrics is not None:
                    group_entry["windows"][window_label] = metrics
            if group_entry["windows"]:
                industry_groups[group_label] = group_entry

    computed_categories = sorted({
        str(v).lower()
        for k, v in category_map.items()
        if k in factors
    })

    data_quality: Dict[str, Any] = {
        "windows_requested": windows or (
            FACTOR_INTELLIGENCE_DEFAULTS.get("returns", {}).get("default_windows")
            or ["1m", "3m", "6m", "1y"]
        ),
        "windows_computed": window_labels,
        "invalid_windows": invalid_windows,
        "factors_analyzed": len(factors),
        "factors_requested": len(chosen_tickers),
        "categories_included": computed_categories,
    }
    if isinstance(industry_info, dict) and industry_info:
        data_quality["unlabeled_industries"] = industry_info.get("unlabeled_industries", 0)
        if industry_info.get("unlabeled_industry_labels") is not None:
            data_quality["unlabeled_industry_labels"] = industry_info.get("unlabeled_industry_labels")

    return {
        "factors": factors,
        "industry_groups": industry_groups,
        "rankings": rankings,
        "by_category": by_category,
        "windows": window_labels,
        "data_quality": data_quality,
        "performance": {
            "factor_returns_ms": int((time.time() - t0) * 1000),
        },
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
            "industry_granularity": industry_granularity,
        },
    }


def compute_macro_composite_matrix(
    returns_panel: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Compute a compact correlation matrix across macro composites:
    equity, fixed_income, cash, commodity, crypto.
    """
    t0 = time.time()
    cats = returns_panel.attrs.get("categories", {})
    tickers_by_cat: Dict[str, List[str]] = {}
    for t, c in cats.items():
        tickers_by_cat.setdefault(c, []).append(t)

    def _ew_series(tickers: List[str]) -> Optional[pd.Series]:
        if not tickers:
            return None
        df = returns_panel.reindex(columns=tickers).dropna()
        if df.empty:
            return None
        return df.mean(axis=1)

    composites: Dict[str, Optional[pd.Series]] = {
        "equity": _ew_series((tickers_by_cat.get("market", []) + tickers_by_cat.get("industry", []) + tickers_by_cat.get("style", []))),
        "fixed_income": _ew_series(tickers_by_cat.get("bond", [])),
        "cash": _ew_series(tickers_by_cat.get("cash", [])),
        "commodity": _ew_series(tickers_by_cat.get("commodity", [])),
        "crypto": _ew_series(tickers_by_cat.get("crypto", [])),
    }

    valid = {k: v for k, v in composites.items() if isinstance(v, pd.Series) and not v.empty}
    if len(valid) < 2:
        return {
            "groups": list(composites.keys()),
            "matrix": pd.DataFrame(),
            "data_quality": {"available_groups": list(valid.keys())},
            "performance": {"macro_composite_ms": int((time.time() - t0) * 1000)},
        }

    df = pd.concat(valid.values(), axis=1)
    df.columns = list(valid.keys())
    df = df.dropna()
    mat = df.corr()
    return {
        "groups": list(valid.keys()),
        "matrix": mat,
        "data_quality": {"available_groups": list(valid.keys()), "obs": int(df.shape[0])},
        "performance": {"macro_composite_ms": int((time.time() - t0) * 1000)},
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
        },
    }


def compute_macro_etf_matrix(
    returns_panel: pd.DataFrame,
    macro_max_per_group: int = 3,
    macro_deduplicate_threshold: float = 0.95,
    macro_min_group_coverage_pct: float = 0.6,
) -> Dict[str, Any]:
    """
    Compute a curated ETF correlation matrix across macro groups with budget
    and de-duplication controls.

    Selection heuristic (deterministic, simple):
      - Sort tickers within each macro group and take up to macro_max_per_group.
      - Build the pool by iterating groups and adding tickers whose correlation to
        already selected ones is below the de-dup threshold.
    """
    t0 = time.time()
    cats = returns_panel.attrs.get("categories", {})
    per_group: Dict[str, List[str]] = {
        "equity": [t for t, c in cats.items() if c in ("market", "industry", "style")],
        "fixed_income": [t for t, c in cats.items() if c == "bond"],
        "cash": [t for t, c in cats.items() if c == "cash"],
        "commodity": [t for t, c in cats.items() if c == "commodity"],
        "crypto": [t for t, c in cats.items() if c == "crypto"],
    }

    selected: List[str] = []
    coverage: Dict[str, Dict[str, Any]] = {}

    # Precompute full correlation for quick de-dup checks
    df_full = returns_panel.dropna()
    corr_full = df_full.corr() if df_full.shape[1] >= 2 else pd.DataFrame()

    for group, tickers in per_group.items():
        tks = sorted(set(tickers))
        coverage[group] = {
            "total": len(tks),
            "selected": 0,
            "quota": macro_max_per_group,
        }
        if not tks:
            continue
        for t in tks:
            if coverage[group]["selected"] >= macro_max_per_group:
                break
            # check de-dup vs already selected
            if selected and not corr_full.empty and t in corr_full.index:
                max_corr = 0.0
                for s in selected:
                    if s in corr_full.columns:
                        try:
                            val = float(corr_full.loc[t, s])
                            if np.isnan(val):
                                continue
                            max_corr = max(max_corr, abs(val))
                        except Exception:
                            continue
                if max_corr >= macro_deduplicate_threshold:
                    continue  # too similar
            # add
            selected.append(t)
            coverage[group]["selected"] += 1

    # Compute correlation matrix for selected set
    if len(selected) < 2:
        return {
            "groups": per_group,
            "matrix": pd.DataFrame(),
            "data_quality": {"selected_count": len(selected), "coverage": coverage},
            "performance": {"macro_etf_ms": int((time.time() - t0) * 1000)},
        }

    df_sel = returns_panel.reindex(columns=selected).dropna()
    mat = df_sel.corr()

    # Coverage stats
    total_groups = len([g for g, stats in coverage.items() if stats["total"] > 0])
    covered_groups = len([g for g, stats in coverage.items() if stats["selected"] > 0])
    coverage_pct = covered_groups / total_groups if total_groups else 0.0

    result = {
        "groups": per_group,
        "matrix": mat,
        "data_quality": {
            "coverage": coverage,
            "selected_count": len(selected),
            "covered_groups": covered_groups,
            "total_groups": total_groups,
            "coverage_pct": round(coverage_pct, 3),
            "dedup_threshold": macro_deduplicate_threshold,
        },
        "performance": {"macro_etf_ms": int((time.time() - t0) * 1000)},
        "analysis_metadata": {
            "start_date": returns_panel.attrs.get("start_date"),
            "end_date": returns_panel.attrs.get("end_date"),
            "universe_hash": returns_panel.attrs.get("universe_hash"),
        },
    }

    # Warn if macro coverage below minimum
    if result["data_quality"]["coverage_pct"] < macro_min_group_coverage_pct:
        result["data_quality"]["warning"] = "low_macro_group_coverage"

    return result
