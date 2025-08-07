"""
Core Data Objects Module

Data structures for portfolio and stock analysis with input validation and caching.

This module provides structured data containers for risk analysis operations.
These objects handle input validation, format standardization, and caching.

Classes:
- StockData: Individual stock analysis configuration with factor model support
- PortfolioData: Portfolio analysis configuration with multi-format input handling

Usage: Foundation objects for portfolio and stock analysis operations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import yaml
import hashlib
import json
from datetime import datetime
import os
import tempfile
import time


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
    - yaml_path: Optional portfolio YAML path for factor proxy lookup
    
    Construction methods:
    - from_ticker(): Basic market regression analysis
    - from_yaml_config(): Inherits factor proxies from portfolio YAML
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
    yaml_path: Optional[str] = None
    
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
            str: MD5 hash of analysis parameters (ticker, dates, factor_proxies, yaml_path)
        """
        return self._cache_key
    
    def _generate_cache_key(self) -> str:
        """Generate cache key for this stock analysis configuration."""
        # Create hash of stock parameters
        key_data = {
            "ticker": self.ticker,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "factor_proxies": self.factor_proxies,
            "yaml_path": self.yaml_path
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
    def from_yaml_config(cls, ticker: str, yaml_path: str,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> 'StockData':
        """
        Create StockData with factor proxies inherited from portfolio YAML configuration.
        
        This method creates stock analysis configuration that inherits factor proxy
        settings from a portfolio YAML file. It's useful for ensuring consistency
        between portfolio-level and stock-level factor model configurations.
        
        Args:
            ticker (str): Stock symbol to analyze
            yaml_path (str): Path to portfolio YAML file containing factor proxies
            start_date (Optional[str]): Analysis start date (overrides YAML if provided)
            end_date (Optional[str]): Analysis end date (overrides YAML if provided)
                
        Returns:
            StockData: Configured for multi-factor analysis using portfolio factor proxies
            
        Example:
            ```python
            # Use portfolio factor configuration
            stock_data = StockData.from_yaml_config("AAPL", "portfolio.yaml")
            
            # Use portfolio factors with custom date range
            stock_data = StockData.from_yaml_config(
                "AAPL", "portfolio.yaml", "2021-01-01", "2023-12-31"
            )
            ```
        """
        return cls(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            yaml_path=yaml_path
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
        return self.factor_proxies is not None or self.yaml_path is not None
    
    def __hash__(self) -> int:
        """Make StockData hashable for caching."""
        return hash(self._cache_key)
    
    def __eq__(self, other) -> bool:
        """Compare StockData objects."""
        if not isinstance(other, StockData):
            return False
        return self._cache_key == other._cache_key


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
            total_weight = sum(self.portfolio_input.values())
            if abs(total_weight - 1.0) > 0.01:
                raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
            
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
            "stock_factor_proxies": self.stock_factor_proxies
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
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return cls(
            portfolio_input=config['portfolio_input'],
            standardized_input=config['portfolio_input'],  # Already standardized in YAML
            start_date=config['start_date'],
            end_date=config['end_date'],
            expected_returns=config.get('expected_returns', {}),
            stock_factor_proxies=config.get('stock_factor_proxies', {})
        )
    
    @classmethod
    def from_holdings(cls, holdings: Dict[str, Union[float, Dict]], 
                     start_date: str, end_date: str,
                     portfolio_name: str,
                     user_id: Optional[int] = None,
                     expected_returns: Optional[Dict[str, float]] = None,
                     stock_factor_proxies: Optional[Dict[str, str]] = None) -> 'PortfolioData':
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
            user_id=user_id
        )
    
    def to_yaml(self, output_path: str) -> None:
        """
        Save portfolio data to YAML configuration file.
        
        Args:
            output_path (str): Path where YAML file will be saved
        """
        config = {
            "portfolio_input": self.standardized_input,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "expected_returns": self.expected_returns,
            "stock_factor_proxies": self.stock_factor_proxies
        }
        
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
    
    def create_risk_limits_temp_file(self, risk_limits: Union[Dict[str, Any], 'RiskLimitsData']) -> str:
        """
        Create collision-safe temporary risk limits file from provided data.
        
        Creates a temporary YAML file containing user-specific risk limits configuration
        using the same collision-safe naming pattern as portfolio temp files.
        
        Args:
            risk_limits (Union[Dict[str, Any], RiskLimitsData]): Risk limits configuration
                in dictionary format or typed RiskLimitsData object
                
        Returns:
            str: Path to created temporary risk limits file (caller responsible for cleanup)
            
        Example:
            # Using RiskLimitsData object
            risk_limits_data = RiskLimitsData(
                portfolio_limits={'max_volatility': 0.20, 'max_loss': -0.15}
            )
            temp_risk_file = portfolio_data.create_risk_limits_temp_file(risk_limits_data)
            
            # Using dictionary
            risk_limits_dict = {'portfolio_limits': {'max_volatility': 0.20}}
            temp_risk_file = portfolio_data.create_risk_limits_temp_file(risk_limits_dict)
        """
        # Convert RiskLimitsData to dict if needed
        if hasattr(risk_limits, 'to_dict'):
            risk_limits_dict = risk_limits.to_dict()
        elif risk_limits:
            risk_limits_dict = risk_limits
        else:
            risk_limits_dict = {}
        
        return self.create_safe_temp_file(risk_limits_dict, "risk_limits", '.yaml')
    
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
        return cls(
            portfolio_limits=data.get('portfolio_limits'),
            concentration_limits=data.get('concentration_limits'),
            variance_limits=data.get('variance_limits'),
            max_single_factor_loss=data.get('max_single_factor_loss'),
            additional_settings={k: v for k, v in data.items() 
                               if k not in ['portfolio_limits', 'concentration_limits', 'variance_limits', 'max_single_factor_loss']},
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


 