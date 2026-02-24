"""
Core Data Objects Module

Data structures for portfolio and stock analysis with input validation and caching.

This module provides structured data containers for risk analysis operations.
These objects handle input validation, format standardization, and caching.

Classes:
- StockData: Individual stock analysis configuration with factor model support
- PortfolioData: Portfolio analysis configuration with multi-format input handling
- PositionsData: Strict container for positions with conversion to PortfolioData

Usage: Foundation objects for portfolio and stock analysis operations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union, Tuple, Callable
from pathlib import Path
import logging
import math
import numbers
import pandas as pd
import yaml
import hashlib
import json
from datetime import datetime
import os
import tempfile
import time


logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_db_loader: Optional[Callable[[], Dict[str, Any]]] = None


def set_db_loader(loader: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """Inject a database loader for cash mappings in standalone-safe way."""
    global _db_loader
    _db_loader = loader


def _load_cash_proxy_map() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load cash proxy mappings with 3-tier fallback.

    Returns:
        (proxy_by_currency, alias_to_currency) where:
        - proxy_by_currency: {currency: proxy_ticker} e.g. {"USD": "SGOV"}
        - alias_to_currency: {broker_ticker: currency} e.g. {"CUR:USD": "USD"}
    """
    try:
        if _db_loader is not None:
            cash_map = _db_loader() or {}
            proxy = cash_map.get("proxy_by_currency", {})
            if proxy:
                return (proxy, cash_map.get("alias_to_currency", {}))
            logger.warning("Cash proxy map: injected DB loader returned empty mappings, trying YAML")
        else:
            from database import get_db_session
            from inputs.database_client import DatabaseClient

            with get_db_session() as conn:
                cash_map = DatabaseClient(conn).get_cash_mappings()
                proxy = cash_map.get("proxy_by_currency", {})
                if proxy:
                    return (proxy, cash_map.get("alias_to_currency", {}))
                logger.warning("Cash proxy map: DB returned empty mappings, trying YAML")
    except Exception as e:
        logger.warning("Cash proxy map: DB unavailable (%s), trying YAML", e)

    try:
        yaml_path = _PROJECT_ROOT / "cash_map.yaml"
        with open(yaml_path, "r") as f:
            cash_map = yaml.safe_load(f) or {}
            return (
                cash_map.get("proxy_by_currency", {}),
                cash_map.get("alias_to_currency", {}),
            )
    except Exception as e:
        logger.warning("Cash proxy map: YAML unavailable (%s), using hardcoded", e)

    return ({"USD": "SGOV"}, {"CUR:USD": "USD"})


@dataclass
class StockData:
    """
    Individual stock analysis configuration with parameter validation and caching.
    
    This data container provides structured input for stock analysis operations,
    supporting both single-factor (market) and multi-factor analysis models.
    
    Parameters:
    - ticker: Stock symbol (automatically normalized to uppercase)
    - start_date/end_date: Optional analysis window
    - factor_proxies: Optional factor model configuration

    
    Construction methods:
    - from_ticker(): Basic market regression analysis

    - from_factor_proxies(): Explicit factor model configuration
    
    Example:
        stock_data = StockData.from_ticker("AAPL", "2020-01-01", "2023-12-31")
        has_factors = stock_data.has_factor_analysis()
        cache_key = stock_data.get_cache_key()
    """
    
    # Core stock analysis parameters
    ticker: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    
    # Factor analysis configuration
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None
    
    # Analysis metadata
    analysis_name: Optional[str] = None
    
    # Caching and metadata
    _cache_key: Optional[str] = None
    _last_updated: Optional[datetime] = None
    
    def __post_init__(self):
        """
        Validate and normalize stock data after initialization.
        
        Validates ticker, normalizes to uppercase, sets default analysis name,
        and generates cache key.
        
        Raises:
            ValueError: If ticker is empty or None
        """
        if not self.ticker:
            raise ValueError("Ticker cannot be empty")
        
        # Normalize ticker to uppercase
        self.ticker = self.ticker.upper()
        
        # Set default analysis name
        if not self.analysis_name:
            self.analysis_name = f"{self.ticker}_analysis"
        
        # Generate cache key
        self._cache_key = self._generate_cache_key()
        self._last_updated = datetime.now()
    
    def get_cache_key(self) -> str:
        """
        Get the cache key for this stock analysis configuration.
        
        Returns:
            str: MD5 hash of analysis parameters (ticker, dates, factor_proxies)
        """
        return self._cache_key
    
    def _generate_cache_key(self) -> str:
        """Generate cache key for this stock analysis configuration."""
        # Create hash of stock parameters
        key_data = {
            "ticker": self.ticker,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "factor_proxies": self.factor_proxies
        }
        
        # Convert to JSON string and hash
        json_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(json_str.encode()).hexdigest()
    
    @classmethod
    def from_ticker(cls, ticker: str, 
                   start_date: Optional[str] = None,
                   end_date: Optional[str] = None) -> 'StockData':
        """
        Create StockData for simple market regression analysis.
        
        This is the most basic construction method for single-stock analysis
        using market regression (stock vs. SPY benchmark). Use this when you
        need straightforward volatility and beta analysis without factor models.
        
        Args:
            ticker (str): Stock symbol to analyze (e.g., "AAPL", "MSFT")
            start_date (Optional[str]): Analysis start date in YYYY-MM-DD format
            end_date (Optional[str]): Analysis end date in YYYY-MM-DD format
                
        Returns:
            StockData: Configured for single-factor market regression analysis
            
        Example:
            ```python
            # Simple market analysis with default date range
            stock_data = StockData.from_ticker("AAPL")
            
            # Market analysis with custom date range
            stock_data = StockData.from_ticker("TSLA", "2020-01-01", "2023-12-31")
            ```
        """
        return cls(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date
        )
    

    @classmethod
    def from_factor_proxies(cls, ticker: str, 
                           factor_proxies: Dict[str, Union[str, List[str]]],
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> 'StockData':
        """
        Create StockData with explicit factor proxies for multi-factor analysis.
        
        This method creates stock analysis configuration with explicitly defined
        factor proxies for comprehensive multi-factor model analysis. Use this
        when you need precise control over factor model specification.
        
        Args:
            ticker (str): Stock symbol to analyze
            factor_proxies (Dict[str, Union[str, List[str]]]): Factor proxy mappings
                Format: {"factor_name": "proxy_ticker"} or {"factor_name": ["proxy1", "proxy2"]}
                Example: {"market": "SPY", "growth": "VUG", "value": "VTV", "momentum": "MTUM"}
            start_date (Optional[str]): Analysis start date in YYYY-MM-DD format
            end_date (Optional[str]): Analysis end date in YYYY-MM-DD format
                
        Returns:
            StockData: Configured for multi-factor analysis with specified factor proxies
            
        Example:
            ```python
            # Multi-factor analysis with style factors
            factor_proxies = {
                "market": "SPY",
                "growth": "VUG", 
                "value": "VTV",
                "momentum": "MTUM",
                "quality": "QUAL"
            }
            stock_data = StockData.from_factor_proxies("AAPL", factor_proxies)
            
            # Multi-factor analysis with custom date range
            stock_data = StockData.from_factor_proxies(
                "TSLA", factor_proxies, "2020-01-01", "2023-12-31"
            )
            ```
        """
        return cls(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            factor_proxies=factor_proxies
        )
    
    def has_factor_analysis(self) -> bool:
        """
        Check if this stock data includes factor analysis configuration.
        
        Determines whether the stock analysis will use multi-factor models
        (complex factor analysis) or simple market regression (single-factor).
        This affects the analysis type and output format.
        
        Returns:
            bool: True if factor proxies or YAML config are provided, False for simple market regression
            
        Analysis Types:
            - True: Multi-factor analysis with factor exposures, R-squared decomposition
            - False: Simple market regression with beta, alpha, correlation vs. SPY
            
        Example:
            ```python
            # Simple market regression
            stock_data = StockData.from_ticker("AAPL")
            has_factors = stock_data.has_factor_analysis()  # False
            
            # Multi-factor analysis
            stock_data = StockData.from_factor_proxies("AAPL", {"market": "SPY", "growth": "VUG"})
            has_factors = stock_data.has_factor_analysis()  # True
            ```
        """
        return self.factor_proxies is not None
    
    def __hash__(self) -> int:
        """Make StockData hashable for caching."""
        return hash(self._cache_key)
    
    def __eq__(self, other) -> bool:
        """Compare StockData objects."""
        if not isinstance(other, StockData):
            return False
        return self._cache_key == other._cache_key


@dataclass
class PositionsData:
    """
    Lightweight container for position data.

    This is the "input" side - holds raw positions and provides
    conversion to PortfolioData for chaining to analysis.
    Validation is strict and fail-fast to surface data issues early.

    Data Contract (required fields per position dict):
    - ticker (str, non-empty)
    - quantity (number, finite)
    - value (number, finite)
    - type (str, non-empty)
    - position_source (str, non-empty; may be comma-delimited after consolidation)
    - currency (str, non-empty)

    Optional fields are passed through for display/transport:
    - name, price, cost_basis, account_id, account_name, brokerage_name, fmp_ticker
    """

    # Core data (internal field names from PositionService)
    positions: List[Dict[str, Any]]

    # Metadata
    user_email: str
    sources: List[str]
    consolidated: bool = True
    as_of: datetime = field(default_factory=datetime.now)

    # Cache metadata (for when cache refactor lands)
    from_cache: bool = False
    cache_age_hours: Optional[float] = None

    # Caching
    _cache_key: Optional[str] = None

    def __post_init__(self):
        """Validate position list and generate cache key."""
        # Fail fast on missing/invalid inputs to avoid masking data issues.
        if self.positions is None:
            raise ValueError("positions must be provided")
        if not isinstance(self.positions, list):
            raise ValueError("positions must be a list of position dicts")
        if self.sources is None:
            raise ValueError("sources must be provided (empty list if none)")
        if not isinstance(self.sources, list):
            raise ValueError("sources must be a list")
        if self.positions and not self.sources:
            raise ValueError("sources cannot be empty when positions are present")
        for src in self.sources:
            if not isinstance(src, str):
                raise ValueError("sources must contain only strings")
            if not src.strip():
                raise ValueError("sources cannot contain empty values")

        required_keys = ["ticker", "quantity", "value", "type", "position_source", "currency"]
        for idx, position in enumerate(self.positions):
            if not isinstance(position, dict):
                raise ValueError(f"positions[{idx}] must be a dict")
            for key in required_keys:
                if key not in position:
                    raise ValueError(f"positions[{idx}] missing required field: {key}")
                if position[key] is None:
                    if key == "currency":
                        position_type = position.get("type")
                        ticker = position.get("ticker", "")
                        if position_type == "cash" or str(ticker).startswith("CUR:"):
                            continue
                    raise ValueError(f"positions[{idx}].{key} cannot be None")
                if isinstance(position[key], str) and position[key].strip() == "":
                    raise ValueError(f"positions[{idx}].{key} cannot be empty")

            ticker = position["ticker"]
            if not isinstance(ticker, str):
                raise ValueError(f"positions[{idx}].ticker must be a string")

            for numeric_key in ("quantity", "value"):
                raw_value = position[numeric_key]
                if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
                    raise ValueError(f"positions[{idx}].{numeric_key} must be numeric")
                if pd.isna(raw_value) or not math.isfinite(float(raw_value)):
                    raise ValueError(f"positions[{idx}].{numeric_key} must be finite")

            for text_key in ("type", "position_source", "currency"):
                if text_key == "currency" and position[text_key] is None:
                    position_type = position.get("type")
                    ticker = position.get("ticker", "")
                    if position_type == "cash" or str(ticker).startswith("CUR:"):
                        continue
                if not isinstance(position[text_key], str):
                    raise ValueError(f"positions[{idx}].{text_key} must be a string")

        self._cache_key = self._generate_cache_key()

    @classmethod
    def from_dataframe(
        cls,
        df: Optional[pd.DataFrame],
        user_email: str,
        sources: Optional[List[str]] = None,
        *,
        consolidated: bool = True,
        as_of: Optional[datetime] = None,
        from_cache: bool = False,
        cache_age_hours: Optional[float] = None,
    ) -> "PositionsData":
        """Create PositionsData from a DataFrame (strict, fail-fast)."""
        if df is None:
            raise ValueError("df must be provided")
        if df.empty:
            raise ValueError("df is empty")

        df_copy = df.copy()
        df_copy = df_copy.where(pd.notnull(df_copy), None)
        positions = df_copy.to_dict(orient="records")

        if sources is None:
            if "position_source" not in df_copy.columns:
                raise ValueError("position_source column required to derive sources")
            raw_sources = df_copy["position_source"].dropna().unique().tolist()
            # Split comma-delimited sources (e.g., "plaid,snaptrade" after consolidation)
            inferred_sources: set = set()
            for raw_src in raw_sources:
                if not isinstance(raw_src, str) or not raw_src.strip():
                    raise ValueError("position_source values must be non-empty strings")
                for src in raw_src.split(","):
                    src = src.strip()
                    if src:
                        inferred_sources.add(src)
            if not inferred_sources:
                raise ValueError("position_source column contains no usable sources")
            sources = sorted(inferred_sources)

        return cls(
            positions=positions,
            user_email=user_email,
            sources=sources,
            consolidated=consolidated,
            as_of=as_of or datetime.now(),
            from_cache=from_cache,
            cache_age_hours=cache_age_hours,
        )

    def to_portfolio_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        portfolio_name: str = "CURRENT_PORTFOLIO",
    ) -> "PortfolioData":
        """Convert positions to PortfolioData for chaining."""
        from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
        from portfolio_risk_engine._ticker import normalize_currency

        if not self.positions:
            return PortfolioData.from_holdings(
                holdings={},
                start_date=start_date or PORTFOLIO_DEFAULTS["start_date"],
                end_date=end_date or PORTFOLIO_DEFAULTS["end_date"],
                portfolio_name=portfolio_name,
            )

        ticker_currencies: Dict[str, set] = {}
        for position in self.positions:
            ticker = position["ticker"]
            currency = position["currency"]
            if ticker not in ticker_currencies:
                ticker_currencies[ticker] = set()
            if currency:
                ticker_currencies[ticker].add(currency)

        for ticker, currencies in ticker_currencies.items():
            if len(currencies) > 1:
                raise ValueError(
                    f"Mixed currencies for {ticker}: {sorted(currencies)}"
                )

        proxy_by_currency, alias_to_currency = _load_cash_proxy_map()
        fmp_ticker_map: Dict[str, str] = {}
        holdings_dict: Dict[str, Dict[str, Any]] = {}
        for position in self.positions:
            ticker = position["ticker"]
            quantity = float(position["quantity"])
            value = float(position["value"])
            currency = position["currency"]
            position_type = position["type"]
            fmp_ticker = position.get("fmp_ticker")

            # Extract cost_basis, handling NaN/None
            raw_cost_basis = position.get("cost_basis")
            cost_basis = None
            if raw_cost_basis is not None:
                try:
                    cb_float = float(raw_cost_basis)
                    if not (cb_float != cb_float):  # Check for NaN
                        cost_basis = cb_float
                except (TypeError, ValueError):
                    pass

            is_cash = position_type == "cash" or ticker.startswith("CUR:")

            if is_cash:
                cash_ccy = alias_to_currency.get(ticker)
                if not cash_ccy:
                    cash_ccy = normalize_currency(currency) if currency else None
                if not cash_ccy and ":" in ticker:
                    cash_ccy = ticker.split(":", 1)[1].upper()
                cash_ccy = cash_ccy or "USD"

                proxy_ticker = proxy_by_currency.get(cash_ccy)
                if proxy_ticker:
                    existing = holdings_dict.get(proxy_ticker)
                    if existing and "shares" in existing:
                        pass
                    else:
                        ticker = proxy_ticker

                if ticker in holdings_dict:
                    holdings_dict[ticker]["dollars"] += float(value)
                    existing_currency = holdings_dict[ticker].get("currency")
                    if existing_currency != currency:
                        raise ValueError(
                            f"Mixed currencies for {ticker}: {existing_currency} vs {currency}"
                        )
                else:
                    holdings_dict[ticker] = {
                        "dollars": float(value),
                        "currency": currency,
                        "type": "cash",
                    }
            else:
                if fmp_ticker:
                    existing_fmp = fmp_ticker_map.get(ticker)
                    if existing_fmp and existing_fmp != fmp_ticker:
                        raise ValueError(
                            f"Conflicting fmp_ticker for {ticker}: {existing_fmp} vs {fmp_ticker}"
                        )
                    fmp_ticker_map[ticker] = fmp_ticker

                if ticker in holdings_dict:
                    holdings_dict[ticker]["shares"] += float(quantity)
                    # Sum cost_basis across positions
                    if cost_basis is not None:
                        existing_cb = holdings_dict[ticker].get("cost_basis")
                        if existing_cb is not None:
                            holdings_dict[ticker]["cost_basis"] = existing_cb + cost_basis
                        else:
                            holdings_dict[ticker]["cost_basis"] = cost_basis
                    if fmp_ticker_map.get(ticker) and "fmp_ticker" not in holdings_dict[ticker]:
                        holdings_dict[ticker]["fmp_ticker"] = fmp_ticker_map[ticker]
                    existing_currency = holdings_dict[ticker].get("currency")
                    if existing_currency != currency:
                        raise ValueError(
                            f"Mixed currencies for {ticker}: {existing_currency} vs {currency}"
                        )
                else:
                    entry = {
                        "shares": float(quantity),
                        "currency": currency,
                        "type": position_type,
                    }
                    if cost_basis is not None:
                        entry["cost_basis"] = cost_basis
                    if fmp_ticker_map.get(ticker):
                        entry["fmp_ticker"] = fmp_ticker_map[ticker]
                    holdings_dict[ticker] = entry

        proxy_tickers = set(proxy_by_currency.values())
        unmapped_cash = [
            t for t, entry in holdings_dict.items()
            if entry.get("type") == "cash" and t not in proxy_tickers
        ]
        for t in unmapped_cash:
            logger.warning(
                "Unmapped cash ticker %s removed from portfolio (no proxy configured)",
                t,
            )
            del holdings_dict[t]

        if not holdings_dict:
            raise ValueError(
                "No positions remaining after cash proxy mapping. "
                "Portfolio contains only unmapped cash holdings."
            )

        currency_map: Dict[str, str] = {}
        for ticker, entry in holdings_dict.items():
            raw_ccy = entry.get("currency", "USD")
            normalized = normalize_currency(raw_ccy) or "USD"
            if normalized != "USD":
                currency_map[ticker] = normalized

        # Auto-detect futures from IBKR exchange mappings.
        # Requires BOTH ticker match and derivative type to avoid equity collisions
        # like "Z" (Zillow equity) vs "Z" (FTSE futures root).
        instrument_types: Dict[str, str] = {}
        try:
            from ibkr.compat import get_ibkr_futures_exchanges

            known_futures = get_ibkr_futures_exchanges()
            derivative_tickers = {
                str(p.get("ticker") or "").strip().upper()
                for p in self.positions
                if str(p.get("type") or "").strip().lower() == "derivative"
                and str(p.get("ticker") or "").strip()
            }
            for ticker in holdings_dict:
                normalized_ticker = str(ticker).strip().upper()
                if normalized_ticker in known_futures and normalized_ticker in derivative_tickers:
                    instrument_types[ticker] = "futures"
        except Exception:
            logger.warning("Failed to auto-detect futures instrument types", exc_info=True)

        portfolio_data = PortfolioData.from_holdings(
            holdings=holdings_dict,
            start_date=start_date or PORTFOLIO_DEFAULTS["start_date"],
            end_date=end_date or PORTFOLIO_DEFAULTS["end_date"],
            portfolio_name=portfolio_name,
            fmp_ticker_map=fmp_ticker_map or None,
            currency_map=currency_map or None,
            instrument_types=instrument_types or None,
        )

        # NOTE: This PortfolioData is for direct-to-risk analysis (CLI --to-risk).
        portfolio_data.user_email = self.user_email

        return portfolio_data

    def get_cache_key(self) -> str:
        """Get the cache key for this positions dataset."""
        if not self._cache_key:
            self._cache_key = self._generate_cache_key()
        return self._cache_key

    def _generate_cache_key(self) -> str:
        """Generate cache key for this positions dataset."""
        key_data = {
            "positions": self.positions,
            "user_email": self.user_email,
            "sources": self.sources,
            "consolidated": self.consolidated,
            "as_of": self.as_of.isoformat() if isinstance(self.as_of, datetime) else str(self.as_of),
        }
        json_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(json_str.encode()).hexdigest()

    def get_tickers(self) -> List[str]:
        """Get list of unique tickers."""
        return sorted({p["ticker"] for p in self.positions})

    def get_total_value(self) -> float:
        """Get total value across positions."""
        total = 0.0
        for position in self.positions:
            raw_value = position["value"]
            if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
                raise ValueError("positions contain non-numeric value")
            if pd.isna(raw_value) or not math.isfinite(float(raw_value)):
                raise ValueError("positions contain invalid value")
            total += float(raw_value)
        return total


@dataclass
class PortfolioData:
    """
    Portfolio configuration with multi-format input support and validation.
    
    This data container handles portfolio input formats and provides automatic
    format detection, validation, and standardization for analysis operations.
    
    Supported Input Formats:
    1. Shares/Dollars: {"AAPL": {"shares": 100}, "SPY": {"dollars": 5000}}
    2. Percentages: {"AAPL": 25.0, "SPY": 75.0} (must sum to ~100%)
    3. Weights: {"AAPL": 0.25, "SPY": 0.75} (must sum to ~1.0)
    4. Mixed: {"AAPL": {"shares": 100}, "SPY": {"weight": 0.3}}
    
    Construction methods:
    - from_yaml(): Load complete configuration from YAML file
    - from_holdings(): Create from holdings dictionary with flexible formats
    
    Example:
        portfolio_data = PortfolioData.from_holdings(
            {"AAPL": 30.0, "MSFT": 25.0, "GOOGL": 20.0, "SGOV": 25.0},
            "2020-01-01", "2023-12-31"
        )
        tickers = portfolio_data.get_tickers()
        weights = portfolio_data.get_weights()
    """
    
    # Raw portfolio input (as provided by user)
    portfolio_input: Dict[str, Union[float, Dict[str, float]]]
    
    # Standardized portfolio input (converted to shares/dollars/weight format)
    standardized_input: Dict[str, Dict[str, float]]
    
    # Portfolio metadata
    start_date: str
    end_date: str
    expected_returns: Dict[str, float]
    stock_factor_proxies: Dict[str, str]
    fmp_ticker_map: Optional[Dict[str, str]] = None
    currency_map: Optional[Dict[str, str]] = None
    instrument_types: Optional[Dict[str, str]] = None
    
    # Portfolio analysis results (populated after standardization)
    weights: Optional[Dict[str, float]] = None
    total_value: Optional[float] = None
    
    # Portfolio name for identification
    portfolio_name: Optional[str] = None
    
    # User identification for portfolio ownership and collision-safe operations
    user_id: Optional[int] = None  # None for CLI/tests, int for API calls
    
    # Caching and metadata
    _cache_key: Optional[str] = None
    _last_updated: Optional[datetime] = None
    
    def __post_init__(self):
        """
        Validate and standardize portfolio input after initialization.
        
        Validates input is not empty, detects format, converts to standardized
        representation, validates allocation sums, and generates cache key.
        
        Raises:
            ValueError: If portfolio input is empty, invalid format, or allocation sums are incorrect
        """
        if not self.portfolio_input:
            raise ValueError("Portfolio input cannot be empty")
            
        # Detect input format and convert to standardized format
        input_format = self._detect_input_format()
        self.standardized_input = self._convert_to_standardized_format(input_format)
        
        # Generate cache key
        self._cache_key = self._generate_cache_key()
        self._last_updated = datetime.now()
    
    def _detect_input_format(self) -> str:
        """Auto-detect the input format based on data structure."""
        if not self.portfolio_input:
            raise ValueError("Portfolio input is empty")
        
        # Check first value to determine format
        first_value = next(iter(self.portfolio_input.values()))
        
        if isinstance(first_value, dict):
            # Check if it has shares/dollars keys
            if any(key in first_value for key in ["shares", "dollars", "value"]):
                return "shares_dollars"
            elif "weight" in first_value:
                return "weights"
            else:
                raise ValueError(f"Unknown dict format: {first_value}")
        
        elif isinstance(first_value, (int, float)):
            # Check if values are percentages (sum ~100) or weights (sum ~1)
            total = sum(self.portfolio_input.values())
            if total > 10:  # Likely percentages
                return "percentages"
            else:  # Likely decimal weights
                return "weights"
        
        else:
            raise ValueError(f"Unsupported value type: {type(first_value)}")
    
    def _convert_to_standardized_format(self, input_format: str) -> Dict[str, Dict[str, float]]:
        """Convert input to standardized portfolio_input format."""
        if input_format == "shares_dollars":
            return self._convert_shares_dollars()
        elif input_format == "percentages":
            return self._convert_percentages()
        elif input_format == "weights":
            return self._convert_weights()
        else:
            raise ValueError(f"Unsupported input format: {input_format}")
    
    def _convert_shares_dollars(self) -> Dict[str, Dict[str, float]]:
        """Convert shares/dollars format to standardized format."""
        standardized = {}
        for ticker, holding in self.portfolio_input.items():
            if isinstance(holding, dict):
                if "shares" in holding:
                    standardized[ticker] = {"shares": float(holding["shares"])}
                elif "dollars" in holding:
                    standardized[ticker] = {"dollars": float(holding["dollars"])}
                elif "value" in holding:
                    standardized[ticker] = {"dollars": float(holding["value"])}
                else:
                    raise ValueError(f"Unknown holding format for {ticker}: {holding}")
            else:
                raise ValueError(f"Expected dict format for {ticker}, got {type(holding)}")
        return standardized
    
    def _convert_percentages(self) -> Dict[str, Dict[str, float]]:
        """Convert percentage allocations to weight format."""
        total_allocation = sum(self.portfolio_input.values())
        if abs(total_allocation - 100) > 1:
            raise ValueError(f"Allocations must sum to 100%, got {total_allocation}%")
        
        standardized = {}
        for ticker, percentage in self.portfolio_input.items():
            weight = percentage / total_allocation
            standardized[ticker] = {"weight": weight}
        
        return standardized
    
    def _convert_weights(self) -> Dict[str, Dict[str, float]]:
        """Convert decimal weights to standardized format."""
        if isinstance(next(iter(self.portfolio_input.values())), dict):
            # Already in weight dict format
            return {ticker: {"weight": float(holding["weight"])} 
                   for ticker, holding in self.portfolio_input.items()}
        else:
            # Simple weight values
            from portfolio_risk_engine._logging import portfolio_logger
            
            total_weight = sum(self.portfolio_input.values())
            if abs(total_weight - 1.0) > 0.01:
                portfolio_logger.info(f"📊 Portfolio weights sum to {total_weight:.3f} (not exactly 1.0 - this is normal for partial scenarios)")
            else:
                portfolio_logger.info(f"📊 Portfolio weights sum to {total_weight:.3f}")
            
            standardized = {}
            for ticker, weight in self.portfolio_input.items():
                standardized[ticker] = {"weight": float(weight)}
            
            return standardized
    
    def get_tickers(self) -> List[str]:
        """
        Get list of portfolio tickers.
        
        Returns:
            List[str]: List of ticker symbols in the portfolio
        """
        return list(self.standardized_input.keys())
    
    def get_weights(self) -> Dict[str, float]:
        """
        Get portfolio weights as decimal values (summing to 1.0).
        
        Returns:
            Dict[str, float]: Portfolio weights as {ticker: weight} mapping
        """
        if self.weights is not None:
            return self.weights
        
        # This would normally be calculated by standardize_portfolio_input
        # For now, return weights from standardized input if available
        weights = {}
        for ticker, holding in self.standardized_input.items():
            if "weight" in holding:
                weights[ticker] = holding["weight"]
        
        return weights
    
    def get_cache_key(self) -> str:
        """
        Get the cache key for this portfolio configuration.
        
        Returns:
            str: MD5 hash of portfolio parameters for cache identification
        """
        return self._cache_key
    
    def _generate_cache_key(self) -> str:
        """Generate cache key for this portfolio configuration with user isolation."""
        # Create hash of portfolio input, dates, and expected returns with user context
        key_data = {
            "user_id": self.user_id,  # Ensures user isolation in cache
            "portfolio_name": self.portfolio_name,
            "portfolio_input": self.standardized_input,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "expected_returns": self.expected_returns,
            "stock_factor_proxies": self.stock_factor_proxies,
            "fmp_ticker_map": self.fmp_ticker_map,
            "currency_map": self.currency_map,
            "instrument_types": self.instrument_types,
        }
        
        # Convert to JSON string and hash
        json_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(json_str.encode()).hexdigest()
    
    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'PortfolioData':
        """
        Create PortfolioData from YAML configuration file.
        
        Args:
            yaml_path (str): Path to YAML configuration file
            
        Returns:
            PortfolioData: Complete portfolio configuration loaded from YAML
        """
        path = Path(yaml_path)
        if not path.is_absolute() and not path.exists():
            candidate = _PROJECT_ROOT / path
            if candidate.exists():
                path = candidate

        with open(path, 'r') as f:
            config = yaml.safe_load(f)
        
        return cls(
            portfolio_input=config['portfolio_input'],
            standardized_input=config['portfolio_input'],  # Already standardized in YAML
            start_date=config['start_date'],
            end_date=config['end_date'],
            expected_returns=config.get('expected_returns', {}),
            stock_factor_proxies=config.get('stock_factor_proxies', {}),
            fmp_ticker_map=config.get("fmp_ticker_map"),
            currency_map=config.get("currency_map"),
            instrument_types=config.get("instrument_types"),
        )
    
    @classmethod
    def from_holdings(cls, holdings: Dict[str, Union[float, Dict]], 
                     start_date: str, end_date: str,
                     portfolio_name: str,
                     user_id: Optional[int] = None,
                     expected_returns: Optional[Dict[str, float]] = None,
                     stock_factor_proxies: Optional[Dict[str, str]] = None,
                     fmp_ticker_map: Optional[Dict[str, str]] = None,
                     currency_map: Optional[Dict[str, str]] = None,
                     instrument_types: Optional[Dict[str, str]] = None) -> 'PortfolioData':
        """
        Create PortfolioData from holdings dictionary with flexible input formats.
        
        Args:
            holdings (Dict[str, Union[float, Dict]]): Portfolio allocation in any supported format
            start_date (str): Analysis start date in YYYY-MM-DD format
            end_date (str): Analysis end date in YYYY-MM-DD format
            portfolio_name (str): Name of the portfolio for database storage
            user_id (Optional[int]): User ID for multi-user isolation (None for CLI/tests)
            expected_returns (Optional[Dict[str, float]]): Expected return forecasts for optimization
            stock_factor_proxies (Optional[Dict[str, str]]): Factor proxy mappings for analysis
            
        Returns:
            PortfolioData: Complete portfolio configuration with standardized input
        """
        return cls(
            portfolio_input=holdings,
            standardized_input={},  # Will be set in __post_init__
            start_date=start_date,
            end_date=end_date,
            expected_returns=expected_returns or {},
            stock_factor_proxies=stock_factor_proxies or {},
            portfolio_name=portfolio_name,
            user_id=user_id,
            fmp_ticker_map=fmp_ticker_map,
            currency_map=currency_map,
            instrument_types=instrument_types,
        )
    
    def to_yaml(self, output_path: str) -> None:
        """
        Save portfolio data to YAML configuration file.

        Args:
            output_path (str): Path where YAML file will be saved
        """
        config = {
            "portfolio_input": self.portfolio_input,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "expected_returns": self.expected_returns,
            "stock_factor_proxies": self.stock_factor_proxies
        }
        if self.fmp_ticker_map:
            config["fmp_ticker_map"] = self.fmp_ticker_map
        if self.currency_map:
            config["currency_map"] = self.currency_map
        if self.instrument_types:
            config["instrument_types"] = self.instrument_types
        
        with open(output_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    def create_temp_file(self, suffix: str = '.yaml') -> str:
        """
        Create collision-safe temporary file for portfolio serialization.
        
        Uses user_id when available to ensure complete isolation between users,
        preventing race conditions and data mixing in multi-user environments.
        
        Args:
            suffix (str): File extension for temporary file (default: '.yaml')
            
        Returns:
            str: Path to created temporary file (caller responsible for cleanup)
            
        Example:
            temp_file = portfolio_data.create_temp_file()
            try:
                # Use temp_file for analysis
                result = analyze_function(temp_file)
            finally:
                os.unlink(temp_file)  # Clean up
        """
        prefix = self._get_safe_prefix()
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, 
                                       prefix=prefix, delete=False) as temp_file:
            self.to_yaml(temp_file.name)
            return temp_file.name
    
    def _get_safe_prefix(self) -> str:
        """
        Generate collision-safe prefix for temporary files.
        
        Creates unique prefixes using user_id, timestamp, and process_id to guarantee
        no collisions between concurrent users or processes.
        
        Returns:
            str: Unique prefix for temporary file naming
        """
        timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
        process_id = os.getpid()
        
        if self.user_id is not None:
            return f"portfolio_user_{self.user_id}_{timestamp}_{process_id}_"
        else:
            # CLI/test mode - still safe but without user separation
            return f"portfolio_anon_{timestamp}_{process_id}_"
    
    def add_ticker(self, ticker: str, position_data: Dict[str, float]) -> None:
        """
        Add a new ticker to the portfolio with proper standardization.
        
        This method safely adds a new ticker to both the raw portfolio_input and 
        the standardized_input, ensuring both representations remain synchronized.
        It also updates the cache key to reflect the portfolio change.
        
        Args:
            ticker (str): Stock symbol to add (will be normalized to uppercase)
            position_data (Dict[str, float]): Position details in any supported format:
                - Shares: {"shares": 100}
                - Dollars: {"dollars": 5000}  
                - Weight: {"weight": 0.25}
                - Mixed: {"shares": 50, "dollars": 1000}
        
        Example:
            portfolio_data.add_ticker("AAPL", {"shares": 100})
            portfolio_data.add_ticker("SPY", {"dollars": 5000})
            portfolio_data.add_ticker("TSLA", {"weight": 0.15})
        
        Raises:
            ValueError: If position_data format is invalid
        """
        ticker = ticker.upper()
        
        # Add to raw portfolio input
        self.portfolio_input[ticker] = position_data.copy()
        
        # Convert to standardized format and add to standardized input
        standardized_position = self._convert_single_position_to_standardized(position_data)
        self.standardized_input[ticker] = standardized_position
        
        # Update cache metadata since portfolio has changed
        self._cache_key = self._generate_cache_key()
        self._last_updated = datetime.now()
    
    def _convert_single_position_to_standardized(self, position_data: Dict[str, float]) -> Dict[str, float]:
        """
        Convert a single position to standardized format.
        
        Args:
            position_data: Single position in any supported format
            
        Returns:
            Standardized position with explicit shares/dollars/weight keys
        """
        # If already in standardized format, return copy
        if any(key in position_data for key in ["shares", "dollars", "value"]):
            standardized = position_data.copy()
            # Normalize 'value' to 'dollars' for consistency
            if "value" in standardized:
                standardized["dollars"] = standardized.pop("value")
            return standardized
        
        # Handle weight format
        elif "weight" in position_data:
            return position_data.copy()
        
        else:
            raise ValueError(f"Invalid position format: {position_data}. Must contain 'shares', 'dollars', 'value', or 'weight'.")
    
    def create_safe_temp_file(self, content: Any, file_type: str = "data", suffix: str = '.yaml') -> str:
        """
        Create collision-safe temporary file for any content with user isolation.
        
        This method can be used for scenario files, configuration files, or any other
        temporary content that needs user-safe naming to prevent race conditions.
        
        Args:
            content (Any): Content to write to the temporary file (will be YAML serialized)
            file_type (str): Type identifier for the temp file (e.g., "scenario", "config")
            suffix (str): File extension for temporary file (default: '.yaml')
            
        Returns:
            str: Path to created temporary file (caller responsible for cleanup)
            
        Example:
            scenario_content = {'new_weights': {'AAPL': 0.4, 'SGOV': 0.6}}
            temp_file = portfolio_data.create_safe_temp_file(scenario_content, "scenario")
            try:
                # Use temp_file for analysis
                result = analyze_function(temp_file)
            finally:
                os.unlink(temp_file)  # Clean up
        """
        import yaml
        
        # Create user-safe prefix with file type
        base_prefix = self._get_safe_prefix()
        typed_prefix = base_prefix.replace("portfolio_", f"{file_type}_")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, 
                                       prefix=typed_prefix, delete=False) as temp_file:
            yaml.dump(content, temp_file, default_flow_style=False)
            return temp_file.name
    
    def __hash__(self) -> int:
        """Make PortfolioData hashable for caching."""
        return hash(self._cache_key)
    
    def __eq__(self, other) -> bool:
        """Compare PortfolioData objects."""
        if not isinstance(other, PortfolioData):
            return False
        return self._cache_key == other._cache_key


@dataclass
class RiskLimitsData:
    """
    Risk limits configuration with validation and serialization support.
    
    This data container handles risk limits in the format expected by risk calculations
    and provides validation, conversion, and standardization for risk limit operations.
    
    Structure matches risk_limits.yaml format:
    - portfolio_limits: Overall portfolio risk constraints
    - concentration_limits: Position size and concentration rules  
    - variance_limits: Factor exposure and variance contribution limits
    - max_single_factor_loss: Maximum loss from any single factor
    - additional_settings: Flexible JSONB storage for custom limits
    
    Example:
        risk_limits = RiskLimitsData(
            portfolio_limits={'max_volatility': 0.25, 'max_loss': -0.15},
            concentration_limits={'max_single_stock_weight': 0.20}
        )
        risk_dict = risk_limits.to_dict()
        risk_limits_from_db = RiskLimitsData.from_dict(db_data)
    """
    
    # Core limit categories (matching risk_limits.yaml structure)
    portfolio_limits: Optional[Dict[str, float]] = None
    concentration_limits: Optional[Dict[str, float]] = None  
    variance_limits: Optional[Dict[str, float]] = None
    max_single_factor_loss: Optional[float] = None
    additional_settings: Optional[Dict[str, Any]] = None
    
    # Metadata
    name: Optional[str] = None  # "Conservative", "Aggressive", "Custom_2024", etc.
    user_id: Optional[int] = None
    portfolio_id: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to risk_limits.yaml format for core risk calculations.
        
        Returns dictionary structure that matches the expected YAML format
        used by run_risk_score_analysis and other core functions.
        
        Returns:
            Dict[str, Any]: Risk limits in YAML format, excluding None values
        """
        result = {}
        
        if self.portfolio_limits:
            result['portfolio_limits'] = self.portfolio_limits.copy()
            
        if self.concentration_limits:
            result['concentration_limits'] = self.concentration_limits.copy()
            
        if self.variance_limits:
            result['variance_limits'] = self.variance_limits.copy()
            
        if self.max_single_factor_loss is not None:
            result['max_single_factor_loss'] = self.max_single_factor_loss
            
        if self.additional_settings:
            result.update(self.additional_settings)
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], user_id: int = None, portfolio_id: int = None, name: str = None) -> 'RiskLimitsData':
        """
        Create RiskLimitsData from dictionary (database or YAML format).
        
        Handles both database row format and risk_limits.yaml format,
        providing flexible construction from various data sources.
        
        Args:
            data (Dict[str, Any]): Risk limits data from database or YAML
            user_id (int, optional): User ID for metadata
            portfolio_id (int, optional): Portfolio ID for metadata  
            name (str, optional): Risk limits profile name
            
        Returns:
            RiskLimitsData: Typed risk limits object
        """
        # Prioritize nested structure (YAML format) if present - it's more complete
        # This handles the case where database returns both flat and nested fields
        if 'portfolio_limits' in data or 'concentration_limits' in data or 'variance_limits' in data:
            return cls._from_yaml_format(data, user_id, portfolio_id, name)
        
        # Fall back to database row format (flat structure) if no nested fields
        return cls._from_database_row(data, user_id, portfolio_id, name)
    
    @classmethod
    def _from_database_row(cls, row: Dict[str, Any], user_id: int = None, portfolio_id: int = None, name: str = None) -> 'RiskLimitsData':
        """Create from database row with flat field structure."""
        portfolio_limits = {}
        if row.get('max_volatility') is not None:
            portfolio_limits['max_volatility'] = float(row['max_volatility'])
        if row.get('max_loss') is not None:
            portfolio_limits['max_loss'] = float(row['max_loss'])
            
        concentration_limits = {}
        if row.get('max_single_stock_weight') is not None:
            concentration_limits['max_single_stock_weight'] = float(row['max_single_stock_weight'])
            
        variance_limits = {}
        if row.get('max_factor_contribution') is not None:
            variance_limits['max_factor_contribution'] = float(row['max_factor_contribution'])
        if row.get('max_market_contribution') is not None:
            variance_limits['max_market_contribution'] = float(row['max_market_contribution'])
        if row.get('max_industry_contribution') is not None:
            variance_limits['max_industry_contribution'] = float(row['max_industry_contribution'])
            
        return cls(
            portfolio_limits=portfolio_limits or None,
            concentration_limits=concentration_limits or None,
            variance_limits=variance_limits or None,
            max_single_factor_loss=float(row['max_single_factor_loss']) if row.get('max_single_factor_loss') is not None else None,
            additional_settings=row.get('additional_settings'),
            name=name or row.get('name'),
            user_id=user_id or row.get('user_id'),
            portfolio_id=portfolio_id or row.get('portfolio_id')
        )
    
    @classmethod  
    def _from_yaml_format(cls, data: Dict[str, Any], user_id: int = None, portfolio_id: int = None, name: str = None) -> 'RiskLimitsData':
        """Create from YAML format with nested structure."""
        core_keys = {
            'portfolio_limits',
            'concentration_limits',
            'variance_limits',
            'max_single_factor_loss',
            'additional_settings',
        }
        extra = {k: v for k, v in data.items() if k not in core_keys}
        raw_additional = data.get('additional_settings', {})
        additional = raw_additional if isinstance(raw_additional, dict) else {}
        if extra:
            additional = {**extra, **additional}

        return cls(
            portfolio_limits=data.get('portfolio_limits'),
            concentration_limits=data.get('concentration_limits'),
            variance_limits=data.get('variance_limits'),
            max_single_factor_loss=data.get('max_single_factor_loss'),
            additional_settings=additional or None,
            name=name,
            user_id=user_id,
            portfolio_id=portfolio_id
        )
    
    def validate(self) -> bool:
        """
        Validate risk limits for logical consistency.
        
        Checks that risk limits make sense (e.g., volatility > 0, 
        loss limits < 0, concentration limits between 0 and 1).
        
        Returns:
            bool: True if limits are valid, False otherwise
        """
        try:
            # Validate portfolio limits
            if self.portfolio_limits:
                if 'max_volatility' in self.portfolio_limits:
                    if self.portfolio_limits['max_volatility'] <= 0:
                        return False
                if 'max_loss' in self.portfolio_limits:
                    if self.portfolio_limits['max_loss'] >= 0:
                        return False
                        
            # Validate concentration limits
            if self.concentration_limits:
                for limit in self.concentration_limits.values():
                    if not (0 < limit <= 1):
                        return False
                        
            # Validate variance limits  
            if self.variance_limits:
                for limit in self.variance_limits.values():
                    if not (0 < limit <= 1):
                        return False
                        
            # Validate factor loss limit
            if self.max_single_factor_loss is not None:
                if self.max_single_factor_loss >= 0:
                    return False
                    
            return True
            
        except (TypeError, ValueError):
            return False
    
    def is_empty(self) -> bool:
        """
        Check if risk limits are effectively empty.
        
        Returns:
            bool: True if no meaningful limits are set
        """
        return (
            not self.portfolio_limits and
            not self.concentration_limits and  
            not self.variance_limits and
            self.max_single_factor_loss is None and
            not self.additional_settings
        )
    
    def get_cache_key(self) -> str:
        """
        Get cache key for this risk limits configuration.
        
        Creates a unique identifier based on risk limits content and metadata
        for use in caching systems. Ensures different risk configurations
        get separate cache entries.
        
        Returns:
            str: MD5 hash of risk limits configuration for cache identification
        """
        import hashlib
        import json
        
        # Create hash of risk limits data with user context
        key_data = {
            "user_id": self.user_id,
            "portfolio_id": self.portfolio_id,
            "name": self.name,
            "portfolio_limits": self.portfolio_limits,
            "concentration_limits": self.concentration_limits,
            "variance_limits": self.variance_limits,
            "max_single_factor_loss": self.max_single_factor_loss,
            "additional_settings": self.additional_settings
        }
        
        # Convert to JSON string and hash
        json_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(json_str.encode()).hexdigest()
    
    def __str__(self) -> str:
        """String representation for debugging."""
        name_part = f" ({self.name})" if self.name else ""
        user_part = f" [user:{self.user_id}]" if self.user_id else ""
        return f"RiskLimitsData{name_part}{user_part}"


 
@dataclass
class FactorAnalysisData:
    """
    Input data object for Factor Intelligence analyses.

    Encapsulates the analysis window and optional flags used by
    factor intelligence service methods. Provides convenience
    constructors that respect global defaults when dates are omitted.
    """

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dates(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs) -> 'FactorAnalysisData':
        from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
        return cls(
            start_date or PORTFOLIO_DEFAULTS.get("start_date"),
            end_date or PORTFOLIO_DEFAULTS.get("end_date"),
            options=kwargs or {}
        )

    @classmethod
    def from_defaults(cls, **kwargs) -> 'FactorAnalysisData':
        from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
        return cls(
            PORTFOLIO_DEFAULTS.get("start_date"),
            PORTFOLIO_DEFAULTS.get("end_date"),
            options=kwargs or {}
        )

    def get_cache_key(self) -> str:
        """Build a deterministic cache key for this analysis input."""
        base = json.dumps({
            "start": self.start_date,
            "end": self.end_date,
            "options": self.options,
        }, sort_keys=True)
        return hashlib.md5(base.encode()).hexdigest()


@dataclass
class PortfolioOffsetsData:
    """
    Centralized input for portfolio-aware factor offset recommendations.

    Encapsulates portfolio weights and analysis parameters with convenience
    helpers for normalization and cache-key hashing.

    Parameters
    ----------
    weights : Dict[str, float]
        Portfolio weights by ticker (not required to sum to 1.0).
    start_date, end_date : Optional[str]
        Analysis window; when None, service defaults apply.
    correlation_threshold : float
        Maximum correlation allowed for offset candidates (≤ 0.0).
    max_recs_per_driver : int
        Maximum recommendations to return for each detected driver (industry/factor).
    industry_granularity : str
        'group' or 'industry' – controls industry driver detection and label mapping.
    """

    weights: Dict[str, float]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    correlation_threshold: float = -0.2
    max_recs_per_driver: int = 5
    industry_granularity: str = "group"

    _cache_key: Optional[str] = None
    _last_updated: Optional[datetime] = None

    def __post_init__(self):
        if not isinstance(self.weights, dict) or not self.weights:
            raise ValueError("weights must be a non-empty {ticker: weight} mapping")
        self.weights = {str(k).upper(): float(v) for k, v in self.weights.items()}
        if self.industry_granularity not in ("group", "industry"):
            self.industry_granularity = "group"
        self._cache_key = self._generate_cache_key()
        self._last_updated = datetime.now()

    def normalized_weights(self) -> Dict[str, float]:
        total = sum(abs(v) for v in self.weights.values())
        if total <= 0:
            return {k: 0.0 for k in self.weights}
        return {k: v / total for k, v in self.weights.items()}

    def _generate_cache_key(self) -> str:
        payload = {
            "weights": self.weights,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "corr": round(float(self.correlation_threshold), 4),
            "max": int(self.max_recs_per_driver),
            "gran": self.industry_granularity,
        }
        js = json.dumps(payload, sort_keys=True)
        return hashlib.md5(js.encode()).hexdigest()

    def get_cache_key(self) -> str:
        return self._cache_key
