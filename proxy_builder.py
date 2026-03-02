#!/usr/bin/env python
# coding: utf-8

# In[ ]:


from gpt_helpers import generate_subindustry_peers
from settings import PORTFOLIO_DEFAULTS          # <— central date window
from utils.ticker_resolver import select_fmp_symbol
import functools
import hashlib
import json
from collections import defaultdict, OrderedDict

# Import logging decorators for proxy builder operations
from utils.logging import (
    log_errors,
    log_operation,
    log_timing,
    database_logger,
    gpt_logger,
    portfolio_logger,
)

# ============================================================================
# LFU CACHE IMPLEMENTATION FOR PROXY DATA
# ============================================================================

class LFUCache:
    """
    LFU (Least Frequently Used) Cache implementation.
    
    This cache evicts the least frequently accessed items when at capacity.
    Perfect for company profiles and GPT peers where popular stocks (AAPL, MSFT)
    should stay cached while obscure stocks get evicted.
    
    Key Features:
    - Frequency-based eviction: Most accessed items stay in cache
    - O(1) get and put operations
    - Cross-user optimization: Popular stocks cached for all users
    - Memory bounded: Automatic cleanup at max capacity
    """
    
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.cache = {}  # key -> value
        self.frequencies = {}  # key -> frequency count
        self.min_frequency = 1
        self.freq_to_keys = defaultdict(OrderedDict)  # frequency -> {key: True, ...}
        
    def get(self, key):
        """Get value and increment frequency."""
        # LOGGING: Add cache access logging with hit/miss tracking
        if key not in self.cache:
            return None
            
        # Increment frequency
        self._increment_frequency(key)
        return self.cache[key]
        
    def put(self, key, value):
        """Put value and handle eviction if needed."""
        if self.maxsize <= 0:
            return
            
        if key in self.cache:
            # Update existing key
            self.cache[key] = value
            self._increment_frequency(key)
            return
            
        # Check if we need to evict
        if len(self.cache) >= self.maxsize:
            self._evict()
            
        # Add new key
        self.cache[key] = value
        self.frequencies[key] = 1
        self.freq_to_keys[1][key] = True
        self.min_frequency = 1
        
    def _increment_frequency(self, key):
        """Increment frequency of a key and update data structures."""
        freq = self.frequencies[key]
        self.frequencies[key] = freq + 1
        
        # Remove from old frequency bucket
        del self.freq_to_keys[freq][key]
        
        # Update min_frequency if this was the last key at min frequency
        if not self.freq_to_keys[freq] and freq == self.min_frequency:
            self.min_frequency += 1
            
        # Add to new frequency bucket
        self.freq_to_keys[freq + 1][key] = True
        
    def _evict(self):
        """Evict the least frequently used key."""
        # Get least frequent key (first in OrderedDict = oldest among ties)
        evict_key = next(iter(self.freq_to_keys[self.min_frequency]))
        
        # Remove from all data structures
        del self.freq_to_keys[self.min_frequency][evict_key]
        del self.cache[evict_key] 
        del self.frequencies[evict_key]
        
    def clear(self):
        """Clear all cache data."""
        self.cache.clear()
        self.frequencies.clear()
        self.freq_to_keys.clear()
        self.min_frequency = 1
        
    def stats(self):
        """Get cache statistics."""
        total_accesses = sum(self.frequencies.values())
        return {
            'cache_type': 'LFU',
            'cache_size': len(self.cache),
            'max_size': self.maxsize,
            'total_accesses': total_accesses,
            'unique_keys': len(self.cache),
            'avg_frequency': total_accesses / len(self.cache) if len(self.cache) > 0 else 0,
            'min_frequency': self.min_frequency
        }

# Global LFU caches for expensive operations
_COMPANY_PROFILE_CACHE = LFUCache(maxsize=1000)  # Keep 1000 most popular company profiles
_GPT_PEERS_CACHE = LFUCache(maxsize=500)         # Keep 500 most popular GPT peer lists

def cache_company_profile(func):
    """
    LFU cache decorator for company profile fetching.
    
    Uses LFU (Least Frequently Used) eviction - keeps most accessed company
    profiles in memory. Popular stocks like AAPL, MSFT stay cached while
    obscure stocks get evicted.
    
    Performance Impact:
    - First call: ~200ms (FMP API call)
    - Frequent calls: ~0.001ms (LFU cache hit)
    - Cross-user benefit: Popular stocks cached for all users
    - Memory bounded: Max 1000 profiles (~5MB)
    """
    @functools.wraps(func)
    def wrapper(ticker):
        # Create cache key
        cache_key = f"profile_{ticker.upper()}"
        
        # Check LFU cache first
        cached_result = _COMPANY_PROFILE_CACHE.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Cache miss - call FMP API
        result = func(ticker)
        
        # Store result in LFU cache
        _COMPANY_PROFILE_CACHE.put(cache_key, result)
        return result
    
    return wrapper

def cache_gpt_peers(func):
    """
    LFU cache decorator for GPT peer generation.
    
    Uses LFU (Least Frequently Used) eviction - keeps most accessed GPT peer
    results in memory. Popular stocks get cached while obscure stocks get evicted.
    
    Performance Impact:
    - First call: ~3-5 seconds (GPT API call + $0.01-0.02 cost)
    - Frequent calls: ~0.001ms (LFU cache hit)  
    - Cost savings: Popular stocks cached across all users
    - Memory bounded: Max 500 peer lists (~1MB)
    """
    @functools.wraps(func)
    def wrapper(ticker, start=None, end=None, fmp_ticker_map=None):
        # Create cache key from all parameters (fmp_ticker_map not included - it's for resolution, not caching)
        cache_data = {
            'ticker': ticker.upper(),
            'start': str(start) if start else None,
            'end': str(end) if end else None
        }

        # Hash the cache data to create unique key
        cache_key = hashlib.md5(json.dumps(cache_data, sort_keys=True).encode()).hexdigest()

        # Check LFU cache first
        cached_result = _GPT_PEERS_CACHE.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Cache miss - call GPT API
        result = func(ticker, start, end, fmp_ticker_map=fmp_ticker_map)

        # Store result in LFU cache
        _GPT_PEERS_CACHE.put(cache_key, result)
        return result
    
    return wrapper

def clear_company_profile_cache():
    """Clear the company profile LFU cache."""
    _COMPANY_PROFILE_CACHE.clear()

def clear_gpt_peers_cache():
    """Clear the GPT peers LFU cache."""
    _GPT_PEERS_CACHE.clear()

def clear_all_proxy_caches():
    """Clear all proxy LFU caches."""
    clear_company_profile_cache()
    clear_gpt_peers_cache()

def get_proxy_cache_stats():
    """Get statistics for all proxy LFU caches."""
    company_stats = _COMPANY_PROFILE_CACHE.stats()
    gpt_stats = _GPT_PEERS_CACHE.stats()
    
    return {
        'company_profiles': {
            **company_stats,
            'cached_tickers': [key.replace('profile_', '') for key in _COMPANY_PROFILE_CACHE.cache.keys()],
            'top_frequencies': sorted(
                [(key.replace('profile_', ''), freq) for key, freq in _COMPANY_PROFILE_CACHE.frequencies.items()],
                key=lambda x: x[1], reverse=True
            )[:10]  # Top 10 most accessed tickers
        },
        'gpt_peers': {
            **gpt_stats,
            'top_frequencies': sorted(
                _GPT_PEERS_CACHE.frequencies.items(),
                key=lambda x: x[1], reverse=True
            )[:5]  # Top 5 most accessed GPT peer requests
        }
    }


# In[ ]:


# file: proxy_builder.py

import requests
import os

# Load API key
FMP_API_KEY = os.getenv("FMP_API_KEY")
BASE_URL = "https://financialmodelingprep.com/stable"

@cache_company_profile
def fetch_profile(ticker: str) -> dict:
    """
    Fetches normalized company profile metadata from Financial Modeling Prep (FMP)
    using the `/stable/profile` endpoint.

    Retrieves and parses the profile for a given ticker symbol, returning key
    fields needed for factor proxy mapping and classification (e.g., exchange, industry, ETF status).

    Parameters
    ----------
    ticker : str
        The stock symbol to query (e.g., "AAPL").

    Returns
    -------
    dict
        A dictionary with keys:
            - 'ticker'     : str  — confirmed symbol (e.g., "AAPL")
            - 'exchange'   : str  — primary listing exchange (e.g., "NASDAQ")
            - 'country'    : str  — country code (e.g., "US")
            - 'industry'   : str  — FMP-defined industry name (e.g., "Consumer Electronics")
            - 'marketCap'  : int  — latest market cap in USD
            - 'isEtf'      : bool — True if classified as an ETF
            - 'isFund'     : bool — True if classified as a mutual fund
            - 'companyName': str  — full company name (e.g., "BlackRock Debt Strategies Fund, Inc.")
            - 'description': str  — detailed company/fund description for AI asset classification

    Raises
    ------
    ValueError
        If the API call fails or returns empty/malformed data.

    Notes
    -----
    • Used by proxy construction and GPT peer logic to determine asset type.
    • ETF and fund flags are useful for excluding non-operating entities from peer analysis.
    • Always returns the requested `ticker` if no symbol is present in payload.
    """
    url = f"{BASE_URL}/profile?symbol={ticker}&apikey={FMP_API_KEY}"
    resp = requests.get(url, timeout=10)
    if not resp.ok:
        raise ValueError(f"FMP API error: {resp.status_code} {resp.text}")

    data = resp.json()
    if not isinstance(data, list) or not data:
        raise ValueError(f"No profile data returned for {ticker}")

    profile = data[0]

    return {
        "ticker": profile.get("symbol", ticker),
        "exchange": profile.get("exchange"),              # e.g. "NASDAQ"
        "country": profile.get("country"),                # e.g. "US"
        "industry": profile.get("industry"),              # e.g. "Consumer Electronics"
        "marketCap": profile.get("marketCap"),            # e.g. 3T
        "isEtf": profile.get("isEtf", False),
        "isFund": profile.get("isFund", False),
        "companyName": profile.get("companyName"),        # e.g. "BlackRock Debt Strategies Fund, Inc."
        "description": profile.get("description"),        # Rich fund/company description for AI classification
    }


# In[ ]:


# file: proxy_builder.py

import yaml

def _resolve_config_path(path: str):
    """
    Resolve config files relative to project root when cwd differs.
    """
    from pathlib import Path

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()

    project_candidate = Path(__file__).resolve().parent / candidate
    if project_candidate.exists():
        return project_candidate.resolve()
    return candidate


def load_exchange_proxy_map(path: str = "exchange_etf_proxies.yaml") -> dict:
    """
    Load exchange-level ETF proxy mappings from database (with YAML fallback).
    Each exchange maps to:
      { market: ETF, momentum: ETF, value: ETF }
    """
    try:
        # Try database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_exchange_mappings()
    except Exception as e:
        # Fallback to YAML
        resolved = _resolve_config_path(path)
        database_logger.warning(f"Database unavailable ({e}), using {resolved} fallback")
        with open(resolved, "r") as f:
            return yaml.safe_load(f)

def map_exchange_proxies(exchange: str, proxy_map: dict) -> dict:
    """
    Given an exchange name and loaded proxy_map, return:
        { market: ..., momentum: ..., value: ... }
    Falls back to proxy_map['DEFAULT'] if no match is found.
    """
    for key in proxy_map:
        if key != "DEFAULT" and key.lower() in exchange.lower():
            return proxy_map[key]
    return proxy_map.get("DEFAULT", {
        "market": "ACWX",
        "momentum": "IMTM",
        "value": "EFV"
    })


# In[ ]:


# file: proxy_builder.py

import yaml

def load_industry_etf_map(path: str = "industry_to_etf.yaml") -> dict:
    """
    Load industry → ETF mappings from database (with YAML fallback).
    """
    try:
        # Try database first
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            return db_client.get_industry_mappings()
    except Exception as e:
        # Fallback to YAML
        resolved = _resolve_config_path(path)
        database_logger.warning(f"Database unavailable ({e}), using {resolved} fallback")
        with open(resolved, "r") as f:
            return yaml.safe_load(f)

def map_industry_etf(industry: str, etf_map: dict) -> str:
    """
    Map a given industry string to its corresponding ETF using the lookup map.
    
    UPDATED: Now handles new structured YAML format
    OLD: {"Gold": "GDX"}
    NEW: {"Gold": {"etf": "GDX", "asset_class": "commodity"}}

    Returns
    -------
    str or None
        Matching ETF ticker from the map. If industry is not found, returns None.

    Notes
    -----
    • No fallback to 'DEFAULT' — this is now handled at the call site,
      where fund/ETF detection can decide whether to skip the assignment.
    • Handles both old format (string) and new format (dict with etf field)
    """
    mapping = etf_map.get(industry)
    if mapping is None:
        return None
    
    # Handle new structured format
    if isinstance(mapping, dict):
        return mapping.get("etf")
    
    # Handle old format (backward compatibility during transition)
    return mapping

def map_industry_asset_class(industry: str, etf_map: dict) -> str:
    """
    Map a given industry string to its corresponding asset class using the lookup map.
    
    NEW FUNCTION: Extracts asset class from extended industry_to_etf.yaml structure
    
    Args:
        industry: Industry name from FMP profile
        etf_map: Dictionary loaded from industry_to_etf.yaml
        
    Returns:
        Asset class string or None if not found
        
    Examples:
        >>> map_industry_asset_class("Gold", {"Gold": {"etf": "GDX", "asset_class": "commodity"}})
        'commodity'
        >>> map_industry_asset_class("Unknown", etf_map)
        None
    """
    mapping = etf_map.get(industry)
    if mapping is None:
        return None
    
    # Handle new structured format
    if isinstance(mapping, dict):
        return mapping.get("asset_class")
    
    # Old format doesn't have asset class info
    return None


# In[ ]:


# file: proxy_builder.py

@log_errors("medium")
@log_timing(1.0)
def build_proxy_for_ticker(
    ticker: str,
    exchange_map: dict,
    industry_map: dict,
    fmp_ticker_map: dict[str, str] | None = None,
) -> dict:
    """
    Constructs a stock_factor_proxies dictionary entry for a single ticker.

    This function:
      • Fetches the company profile from FMP using the provided ticker.
      • Maps the exchange to market/momentum/value ETFs using `exchange_map`.
      • If the stock is not an ETF or fund, maps the industry to an ETF using `industry_map`
        and initializes a placeholder subindustry list.
      • For ETFs or funds, sets both `industry` and `subindustry` to None or empty.

    Parameters
    ----------
    ticker : str
        The stock ticker symbol (e.g., "AAPL").
    exchange_map : dict
        Dictionary loaded from `exchange_etf_proxies.yaml`, mapping exchange names
        to ETF proxies (keys: market, momentum, value).
    industry_map : dict
        Dictionary loaded from `industry_to_etf.yaml`, mapping industry names
        to representative ETFs.

    Returns
    -------
    dict
        A dictionary with the structure:
        {
            "market": str,
            "momentum": str,
            "value": str,
            "industry": Optional[str],
            "subindustry": list
        }

    Example
    -------
    {
        "market": "SPY",
        "momentum": "MTUM",
        "value": "IWD",
        "industry": "IGV",          # or empty if ETF
        "subindustry": []           # or empty if ETF
    }

    Notes
    -----
    • ETFs or funds are assigned themselves as their industry proxy 
      only if they are not already serving as the market proxy.
    • If the FMP profile fetch fails, the function returns None.
    • Unrecognized industries default to industry_map['DEFAULT'], if defined.
    """
    # LOGGING: Add proxy building start logging with ticker and timing
    from utils.logging import log_critical_alert
    fmp_symbol = select_fmp_symbol(ticker, fmp_ticker_map=fmp_ticker_map)
    try:
        profile = fetch_profile(fmp_symbol)
    except Exception as e:
        # LOGGING: Add profile fetch error logging with ticker and error details
        log_critical_alert(
            "profile_fetch_failure",
            "medium",
            f"Profile fetch failed for {ticker}",
            "Check ticker validity and API connectivity",
            details={"ticker": ticker, "fmp_ticker": fmp_symbol, "error": str(e)},
        )
        gpt_logger.warning(f"⚠️ {ticker}: profile fetch failed — {e}")
        return None

    proxies = {}

    # LOGGING: Add exchange mapping logging with exchange and mapped proxies
    # Add exchange-based factors (always)
    proxies.update(map_exchange_proxies(profile.get("exchange", ""), exchange_map))

    # LOGGING: Add industry mapping logging with ETF/fund detection and industry assignment
    # Assign industry to itself only if it's an ETF/fund AND not already used as market proxy
    # Else, add industry proxy ETF
    if profile.get("isEtf") or profile.get("isFund"):
        market_proxy = proxies.get("market", "").upper()
        if ticker.upper() != market_proxy:
            proxies["industry"] = ticker.upper()
        # else: don't set industry proxy for market proxy ETFs (prevents empty string)
        proxies["subindustry"] = []
    else:
        industry = profile.get("industry")
        # LOGGING: Add industry ETF mapping logging with industry name and mapped ETF
        proxies["industry"] = map_industry_etf(industry, industry_map) if industry else ""
        proxies["subindustry"] = []

    return proxies


# In[ ]:


# file: proxy_builder.py

import yaml
from pathlib import Path

def inject_proxies_into_portfolio_yaml(path: str = "portfolio.yaml") -> None:
    """
    Populates the `stock_factor_proxies` section of a portfolio YAML file using exchange
    and industry mappings.

    For each ticker listed in `portfolio_input`, this function:
      - Retrieves the company profile via FMP.
      - Maps the exchange to market/momentum/value ETFs (via `exchange_etf_proxies.yaml`).
      - Maps the industry to an ETF (via `industry_to_etf.yaml`).
      - Adds a placeholder `subindustry: []` entry.
      - Stores results in the `stock_factor_proxies` block of the YAML.

    Parameters
    ----------
    path : str, optional
        Path to the portfolio YAML file. Defaults to "portfolio.yaml".

    Raises
    ------
    FileNotFoundError
        If the specified YAML file does not exist.
    ValueError
        If the YAML file does not contain a valid `portfolio_input` block.

    Side Effects
    ------------
    • Overwrites the YAML file in-place with updated `stock_factor_proxies`.
    • Prints the number of tickers updated.
    • Logs warnings for tickers that fail profile retrieval.

    Example
    -------
    >>> inject_proxies_into_portfolio_yaml("my_portfolio.yaml")
    ✅ Updated stock_factor_proxies for 4 tickers in my_portfolio.yaml
    """
    # Load YAML
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} not found")

    with open(p, "r") as f:
        cfg = yaml.safe_load(f)

    tickers = list(cfg.get("portfolio_input", {}).keys())
    if not tickers:
        raise ValueError("portfolio_input is empty or missing")
    fmp_ticker_map = cfg.get("fmp_ticker_map") or {}

    # Load reference maps
    exchange_map = load_exchange_proxy_map()
    industry_map = load_industry_etf_map()

    # Build proxies
    stock_proxies = {}
    for t in tickers:
        proxy = build_proxy_for_ticker(t, exchange_map, industry_map, fmp_ticker_map=fmp_ticker_map)
        if proxy:
            stock_proxies[t] = proxy
        else:
            portfolio_logger.warning(f"⚠️ Skipping {t} due to missing profile")

    # Update and write back
    cfg["stock_factor_proxies"] = stock_proxies
    with open(p, "w") as f:
        yaml.dump(cfg, f, sort_keys=False)

    portfolio_logger.info(f"✅ Updated stock_factor_proxies for {len(stock_proxies)} tickers in {path}")


# In[ ]:


# file: proxy_builder.py

from typing import List
import pandas as pd

from data_loader import fetch_monthly_close      # already cached disk-layer

def filter_valid_tickers(
    cands: List[str],
    target_ticker: str,
    start: pd.Timestamp | None = None,
    end:   pd.Timestamp | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
) -> List[str]:
    """
    Return only those peer tickers that have *at least* as many monthly
    return observations as `target_ticker` over the same date window.

    Parameters
    ----------
    cands : list[str]
        Raw peer symbols (e.g. ['AAPL', 'XYZ', …]).
    target_ticker : str
        The stock we’re building the proxy for.  Its own data length sets
        the minimum observations all peers must match.
    start, end : pd.Timestamp | None
        Optional overrides for the analysis window.  Defaults fall back to
        PORTFOLIO_DEFAULTS.

    Returns
    -------
    list[str]
        Upper-cased symbols that satisfy the length requirement and loaded
        cleanly from `fetch_monthly_close`.
    """
    start = pd.to_datetime(start or PORTFOLIO_DEFAULTS["start_date"])
    end   = pd.to_datetime(end   or PORTFOLIO_DEFAULTS["end_date"])
    
    target_ticker = target_ticker.upper()
    target_obs = None

    # ▸ Observation count of the target
    target_prices = fetch_monthly_close(
        target_ticker,
        start,
        end,
        fmp_ticker_map=fmp_ticker_map,
    )
    target_obs  = len(target_prices)

    good: List[str] = []
    
    for sym in cands:
        try:
            prices = fetch_monthly_close(
                sym,
                start,
                end,
                fmp_ticker_map=fmp_ticker_map,
            )

            # Basic validation: sufficient prices for returns calculation
            from settings import DATA_QUALITY_THRESHOLDS
            min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_peer_validation"]
            
            if not (isinstance(prices, pd.Series) and len(prices.dropna()) >= min_obs):
                continue

            # Enhanced validation: check observation count vs. target ticker
            if len(prices) >= target_obs:
                good.append(sym.upper())
                
        except Exception as e:
            # Any fetch failure (network, malformed payload, etc.) → skip
            gpt_logger.warning(f"⚠️  Failed to validate ticker {sym}: {type(e).__name__}: {e}")
            continue

    return good


# In[ ]:


# file: proxy_builder.py

import ast

@log_errors("high")
@cache_gpt_peers
def get_subindustry_peers_from_ticker(
    ticker: str,
    start: pd.Timestamp | None = None,
    end:   pd.Timestamp | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
) -> list[str]:
    """
    Gets subindustry peer tickers with database-first caching, following the same pattern
    as load_exchange_proxy_map() and load_industry_etf_map().

    This function:
    • First checks the subindustry_peers database table for cached results
    • If found, returns the cached peer list immediately
    • If not found, fetches company metadata from FMP and checks if ticker is ETF/fund
    • For stocks, generates peers via GPT and caches the result in the database
    • Filters results to include only real, currently listed tickers

    Parameters
    ----------
    ticker : str
        Stock symbol to generate peer group for.
        
    start: pd.Timestamp | None = None
    end:   pd.Timestamp | None = None
        Dates to validate peer tickers have sufficient observations.

    Returns
    -------
    list[str]
        Cleaned list of valid peer tickers (strings). Empty if parsing fails, the symbol is an ETF/fund,
        or if no valid peers are returned.

    Notes
    -----
    • Database-first approach prevents duplicate GPT calls across portfolios and users
    • Skips GPT call entirely for ETFs and mutual funds (via FMP profile check)
    • Uses `ast.literal_eval()` to safely parse GPT output
    • Calls `filter_valid_tickers()` to enforce only valid symbols from FMP
    • Caches all successful results to the global subindustry_peers table

    Side Effects
    ------------
    • Queries and updates the subindustry_peers database table
    • Prints database status and any GPT generation messages
    • Logs skip message for ETFs/funds
    """
    # ─── 0.  Resolve dates (falls back to defaults) ────────────────
    start = pd.to_datetime(start or PORTFOLIO_DEFAULTS["start_date"])
    end   = pd.to_datetime(end   or PORTFOLIO_DEFAULTS["end_date"])
    
    ticker = ticker.upper()

    # ─── 1. Try database first (same pattern as load_exchange_proxy_map) ────────────────
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            cached_peers = db_client.get_subindustry_peers(ticker)
            if cached_peers is not None:
                database_logger.debug(f"Using cached subindustry peers for {ticker} ({len(cached_peers)} peers)")
                return cached_peers
    except Exception as e:
        database_logger.warning(f"Database unavailable for {ticker} ({e}), generating fresh peers")

    # ─── 2. Generate fresh peers via GPT (original logic) ────────────────
    try:
        fmp_symbol = select_fmp_symbol(ticker, fmp_ticker_map=fmp_ticker_map)
        profile = fetch_profile(fmp_symbol)

        # Skip peer generation for ETFs and funds
        if profile.get("isEtf") or profile.get("isFund"):
            gpt_logger.debug(f"Skipping GPT peers for {ticker} (ETF or fund)")
            # Cache empty result for ETFs/funds to avoid repeated FMP calls
            try:
                with get_db_session() as conn:
                    db_client = DatabaseClient(conn)
                    db_client.save_subindustry_peers(ticker, [], source='etf_fund_skip')
            except Exception:
                pass  # Continue even if cache save fails
            return []
            
        name = profile.get("companyName") or profile.get("name") or ticker
        industry = profile.get("industry", "Unknown")

        raw_peers_text = generate_subindustry_peers(ticker=ticker, name=name, industry=industry)
        gpt_logger.debug(f"GPT peers for {ticker}: {raw_peers_text}")

        peer_list = ast.literal_eval(raw_peers_text)

        if not isinstance(peer_list, list):
            raise ValueError("Parsed object is not a list")

        # ▶ pass dates through so peer data screening uses **same window**
        filtered_peers = filter_valid_tickers(
            peer_list, 
            target_ticker=ticker,
            start=start,
            end=end,
            fmp_ticker_map=fmp_ticker_map,
        )

        # ─── 3. Cache result for future use (same pattern as factor_proxy_service) ────────────────
        try:
            with get_db_session() as conn:
                db_client = DatabaseClient(conn)
                db_client.save_subindustry_peers(ticker, filtered_peers, source='gpt')
            database_logger.debug(f"Cached {len(filtered_peers)} subindustry peers for {ticker}")
        except Exception as e:
            database_logger.warning(f"Failed to cache peers for {ticker}: {e}")
            # Continue even if save fails

        return filtered_peers

    except Exception as e:
        gpt_logger.error(f"{ticker}: failed to generate peers — {e}")
        return []


# In[ ]:


# file: proxy_builder.py

import yaml
from pathlib import Path

def inject_subindustry_peers_into_yaml(
    yaml_path: str = "portfolio.yaml",
    tickers: list[str] = None
) -> None:
    """
    Generates subindustry peer groups via GPT for tickers in a portfolio YAML file.

    This function updates the `stock_factor_proxies` section of the YAML file by adding
    a `subindustry` key for each ticker. It uses the GPT-based peer generation function
    (`get_subindustry_peers_from_ticker`) to generate peer lists based on company name
    and industry.

    Parameters
    ----------
    yaml_path : str, default "portfolio.yaml"
        Path to the portfolio YAML file. The file must contain a `portfolio_input` section.

    tickers : list[str], optional
        List of tickers to update. If None, updates all tickers in `portfolio_input`.

    Raises
    ------
    FileNotFoundError
        If the specified YAML file does not exist.

    Side Effects
    ------------
    • Overwrites the YAML file in place.
    • Adds or updates the `subindustry` field under `stock_factor_proxies` for each ticker.
    • Prints progress and peer count for each ticker to stdout.
    """
    # ── Load YAML
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"{yaml_path} not found")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    tickers_to_process = tickers or list(config.get("portfolio_input", {}).keys())
    stock_proxies = config.get("stock_factor_proxies", {})
    fmp_ticker_map = config.get("fmp_ticker_map") or {}

    for tkr in tickers_to_process:
        peers = get_subindustry_peers_from_ticker(tkr, fmp_ticker_map=fmp_ticker_map)
        if tkr not in stock_proxies:
            stock_proxies[tkr] = {}
        stock_proxies[tkr]["subindustry"] = peers
        gpt_logger.info(f"✅ {tkr} → {len(peers)} peers")

    config["stock_factor_proxies"] = stock_proxies

    with open(path, "w") as f:
        yaml.dump(config, f, sort_keys=False)

    gpt_logger.info(f"\n✅ Finished writing subindustry peers to {yaml_path}")


# In[1]:


# file: proxy_builder.py

import yaml
from pathlib import Path

@log_errors("medium")
@log_operation("proxy_injection")
@log_timing(2.0)
def inject_all_proxies(
    yaml_path: str = "portfolio.yaml",
    use_gpt_subindustry: bool = False
) -> None:
    """
    Injects factor proxy mappings into a portfolio YAML file.

    For each ticker in `portfolio_input`, this function builds and injects:
      - Market, momentum, and value proxies based on exchange
      - Industry ETF proxy based on industry classification
      - (Optional) Subindustry peer list generated via GPT

    Parameters
    ----------
    yaml_path : str, default "portfolio.yaml"
        Path to the portfolio YAML file. The file must include a `portfolio_input` section.
    
    use_gpt_subindustry : bool, default False
        If True, sends company name + industry to GPT to generate subindustry peer tickers,
        and injects them into the `subindustry` field for each stock. Otherwise, the subindustry
        field is left empty (or populated from other means).

    Raises
    ------
    FileNotFoundError
        If the YAML file does not exist.
    
    ValueError
        If the YAML file lacks a `portfolio_input` section.

    Side Effects
    ------------
    Overwrites the YAML file in place, populating the `stock_factor_proxies` section.
    Prints progress to stdout for each ticker processed.
    """
    # LOGGING: Add proxy injection timing
    # LOGGING: Add industry mapping logging
    # LOGGING: Add peer discovery logging
    # LOGGING: Add data validation logging
    # LOGGING: Add proxy building timing
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"{yaml_path} not found")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    tickers = list(config.get("portfolio_input", {}).keys())
    if not tickers:
        raise ValueError("No portfolio_input found in YAML.")
    fmp_ticker_map = config.get("fmp_ticker_map") or {}

    start_date = pd.to_datetime(config.get("start_date", PORTFOLIO_DEFAULTS["start_date"]))
    end_date   = pd.to_datetime(config.get("end_date",   PORTFOLIO_DEFAULTS["end_date"]))

    exchange_map = load_exchange_proxy_map()
    industry_map = load_industry_etf_map()
    stock_proxies = {}

    for tkr in tickers:
        proxy = build_proxy_for_ticker(tkr, exchange_map, industry_map, fmp_ticker_map=fmp_ticker_map)
        if proxy:
            stock_proxies[tkr] = proxy
        else:
            portfolio_logger.warning(f"⚠️ Skipping {tkr} due to profile error.")

    config["stock_factor_proxies"] = stock_proxies

    # DEBUG: Check expected_returns before and after processing
    from utils.logging import portfolio_logger
    portfolio_logger.debug(f"🔍 Before YAML write: expected_returns = {config.get('expected_returns')} (type: {type(config.get('expected_returns'))})")

    # Optional: enrich with GPT subindustry peers
    if use_gpt_subindustry:
        from proxy_builder import get_subindustry_peers_from_ticker
        for tkr in tickers:
            peers = get_subindustry_peers_from_ticker(
                tkr,
                start=start_date,
                end=end_date,
                fmp_ticker_map=fmp_ticker_map,
            )
            stock_proxies[tkr]["subindustry"] = peers
            gpt_logger.info(f"✅ {tkr} → {len(peers)} GPT peers")

    # Save updated YAML
    with open(path, "w") as f:
        yaml.dump(config, f, sort_keys=False)

    # DEBUG: Check what was actually written to the file
    with open(path, "r") as f:
        saved_config = yaml.safe_load(f)
    portfolio_logger.debug(f"🔍 After YAML write: expected_returns = {saved_config.get('expected_returns')} (type: {type(saved_config.get('expected_returns'))})")

    portfolio_logger.info(f"\n✅ All proxies injected into {yaml_path}")


# In[ ]:
