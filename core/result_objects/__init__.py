"""Result objects for structured service layer responses.

This package provides typed result objects for all service-layer outputs.
Classes are organized by domain in submodules, but all are re-exported
here for backward compatibility. Existing imports continue to work:

    from core.result_objects import RiskAnalysisResult, PositionResult
"""

from ._helpers import (
    _convert_to_json_serializable,
    _clean_nan_values,
    _format_df_as_text,
    _abbreviate_label,
    _abbreviate_labels,
    _DEFAULT_INDUSTRY_ABBR_MAP,
)
from .positions import PositionResult
from .risk import RiskAnalysisResult, RiskScoreResult
from .performance import PerformanceResult
from .realized_performance import (
    RealizedIncomeMetrics,
    RealizedPnlBasis,
    RealizedMetadata,
    RealizedPerformanceResult,
)
from .optimization import OptimizationResult
from .whatif import WhatIfResult
from .stock_analysis import StockAnalysisResult
from .basket import BasketAnalysisResult
from .interpretation import InterpretationResult
from .factor_intelligence import (
    FactorCorrelationResult,
    FactorPerformanceResult,
    FactorReturnsResult,
    OffsetRecommendationResult,
    PortfolioOffsetRecommendationResult,
)

__all__ = [
    "PositionResult",
    "RiskAnalysisResult",
    "RiskScoreResult",
    "PerformanceResult",
    "RealizedIncomeMetrics",
    "RealizedPnlBasis",
    "RealizedMetadata",
    "RealizedPerformanceResult",
    "OptimizationResult",
    "WhatIfResult",
    "StockAnalysisResult",
    "BasketAnalysisResult",
    "InterpretationResult",
    "FactorCorrelationResult",
    "FactorPerformanceResult",
    "FactorReturnsResult",
    "OffsetRecommendationResult",
    "PortfolioOffsetRecommendationResult",
]
