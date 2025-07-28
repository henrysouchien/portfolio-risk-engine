"""Custom exceptions for the risk module."""


class RiskModuleException(Exception):
    """Base exception for all risk module errors."""
    pass


class ValidationError(RiskModuleException):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, data=None):
        super().__init__(message)
        self.data = data


class PortfolioValidationError(RiskModuleException):
    """Raised when portfolio data is invalid."""
    
    def __init__(self, message: str, portfolio_data=None):
        super().__init__(message)
        self.portfolio_data = portfolio_data


class PortfolioAnalysisError(RiskModuleException):
    """Raised when portfolio analysis fails."""
    
    def __init__(self, message: str, portfolio_data=None):
        super().__init__(message)
        self.portfolio_data = portfolio_data


class RiskConfigValidationError(RiskModuleException):
    """Raised when risk configuration is invalid."""
    
    def __init__(self, message: str, risk_config=None):
        super().__init__(message)
        self.risk_config = risk_config


class ScenarioValidationError(RiskModuleException):
    """Raised when scenario data is invalid."""
    
    def __init__(self, message: str, scenario_data=None):
        super().__init__(message)
        self.scenario_data = scenario_data


class ScenarioAnalysisError(RiskModuleException):
    """Raised when scenario analysis fails."""
    
    def __init__(self, message: str, scenario_data=None):
        super().__init__(message)
        self.scenario_data = scenario_data


class StockAnalysisError(RiskModuleException):
    """Raised when stock analysis fails."""
    
    def __init__(self, message: str, ticker=None):
        super().__init__(message)
        self.ticker = ticker


class DataLoadingError(RiskModuleException):
    """Raised when data loading fails."""
    
    def __init__(self, message: str, source=None):
        super().__init__(message)
        self.source = source


class AnalysisError(RiskModuleException):
    """Raised when analysis calculation fails."""
    
    def __init__(self, message: str, analysis_type=None):
        super().__init__(message)
        self.analysis_type = analysis_type


class OptimizationError(RiskModuleException):
    """Raised when portfolio optimization fails."""
    
    def __init__(self, message: str, optimization_type=None):
        super().__init__(message)
        self.optimization_type = optimization_type


class TempFileError(RiskModuleException):
    """Raised when temporary file operations fail."""
    
    def __init__(self, message: str, file_path=None):
        super().__init__(message)
        self.file_path = file_path


class ServiceError(RiskModuleException):
    """Raised when service layer operations fail."""
    
    def __init__(self, message: str, service_name=None):
        super().__init__(message)
        self.service_name = service_name


class CacheError(RiskModuleException):
    """Raised when cache operations fail."""
    
    def __init__(self, message: str, cache_key=None):
        super().__init__(message)
        self.cache_key = cache_key 