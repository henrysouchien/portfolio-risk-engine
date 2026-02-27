"""Basket analysis result objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from utils.serialization import make_json_safe


@dataclass
class BasketAnalysisResult:
    """Structured basket returns analysis payload."""

    basket_name: str
    description: Optional[str]
    tickers: List[str]
    resolved_weights: Dict[str, float]
    weighting_method: str
    performance: Dict[str, Any]
    component_returns: Dict[str, Dict[str, float]]
    correlation_matrix: Dict[str, Dict[str, float]]
    basket_to_portfolio_corr: Optional[float]
    data_coverage: Dict[str, Any]
    analysis_period: Dict[str, Any]
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    warnings: List[str] = field(default_factory=list)

    def _component_extremes(self) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.component_returns:
            return None, None

        ranked = sorted(
            self.component_returns.items(),
            key=lambda item: float(item[1].get("contribution", 0.0)),
            reverse=True,
        )
        top_ticker, top_data = ranked[0]
        bottom_ticker, bottom_data = ranked[-1]
        return (
            {
                "ticker": top_ticker,
                "total_return_pct": round(float(top_data.get("total_return", 0.0)) * 100, 2),
                "contribution_pct": round(float(top_data.get("contribution", 0.0)) * 100, 2),
                "weight_pct": round(float(top_data.get("weight", 0.0)) * 100, 2),
            },
            {
                "ticker": bottom_ticker,
                "total_return_pct": round(float(bottom_data.get("total_return", 0.0)) * 100, 2),
                "contribution_pct": round(float(bottom_data.get("contribution", 0.0)) * 100, 2),
                "weight_pct": round(float(bottom_data.get("weight", 0.0)) * 100, 2),
            },
        )

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact basket metrics payload for agent-oriented responses."""
        perf_returns = (self.performance or {}).get("returns", {})
        perf_risk = (self.performance or {}).get("risk_metrics", {})
        perf_risk_adj = (self.performance or {}).get("risk_adjusted_returns", {})
        perf_benchmark = (self.performance or {}).get("benchmark_analysis", {})

        top_component, bottom_component = self._component_extremes()
        max_weight = max((abs(w) for w in self.resolved_weights.values()), default=0.0)
        excluded_tickers = list(self.data_coverage.get("excluded_tickers") or [])
        available_tickers = list(self.data_coverage.get("available_tickers") or [])

        snapshot = {
            "basket": {
                "name": self.basket_name,
                "description": self.description,
                "weighting_method": self.weighting_method,
                "ticker_count": len(self.tickers),
            },
            "period": {
                "start_date": self.analysis_period.get("start_date"),
                "end_date": self.analysis_period.get("end_date"),
                "months": self.analysis_period.get("total_months"),
            },
            "performance": {
                "benchmark_ticker": perf_benchmark.get("benchmark_ticker"),
                "total_return_pct": perf_returns.get("total_return"),
                "annualized_return_pct": perf_returns.get("annualized_return"),
                "volatility_pct": perf_risk.get("volatility"),
                "sharpe_ratio": perf_risk_adj.get("sharpe_ratio"),
                "max_drawdown_pct": perf_risk.get("maximum_drawdown"),
                "alpha_annual_pct": perf_benchmark.get("alpha_annual"),
                "beta": perf_benchmark.get("beta"),
            },
            "components": {
                "max_weight_pct": round(max_weight * 100, 2),
                "top_component": top_component,
                "bottom_component": bottom_component,
            },
            "portfolio": {
                "correlation": self.basket_to_portfolio_corr,
            },
            "data_coverage": {
                "available_tickers": available_tickers,
                "excluded_tickers": excluded_tickers,
                "available_count": len(available_tickers),
                "excluded_count": len(excluded_tickers),
                "coverage_pct": self.data_coverage.get("coverage_pct"),
            },
            "warnings": list(self.warnings or []),
        }
        return make_json_safe(snapshot)

    def get_summary(self) -> Dict[str, Any]:
        """Get key basket performance metrics summary."""
        perf_returns = (self.performance or {}).get("returns", {})
        perf_risk = (self.performance or {}).get("risk_metrics", {})
        perf_risk_adj = (self.performance or {}).get("risk_adjusted_returns", {})
        perf_benchmark = (self.performance or {}).get("benchmark_analysis", {})
        contribution_sum = sum(
            float(component.get("contribution", 0.0))
            for component in (self.component_returns or {}).values()
        )

        return make_json_safe(
            {
                "basket_name": self.basket_name,
                "benchmark_ticker": perf_benchmark.get("benchmark_ticker"),
                "total_return_pct": perf_returns.get("total_return"),
                "annualized_return_pct": perf_returns.get("annualized_return"),
                "volatility_pct": perf_risk.get("volatility"),
                "sharpe_ratio": perf_risk_adj.get("sharpe_ratio"),
                "max_drawdown_pct": perf_risk.get("maximum_drawdown"),
                "alpha_annual_pct": perf_benchmark.get("alpha_annual"),
                "beta": perf_benchmark.get("beta"),
                "component_contribution_sum_pct": round(contribution_sum * 100, 2),
            }
        )

    def to_api_response(self) -> Dict[str, Any]:
        """Convert BasketAnalysisResult to full API response format."""
        payload = {
            "analysis_type": "basket_returns",
            "basket_name": self.basket_name,
            "description": self.description,
            "tickers": list(self.tickers),
            "resolved_weights": dict(self.resolved_weights),
            "weighting_method": self.weighting_method,
            "analysis_period": dict(self.analysis_period),
            "performance": dict(self.performance or {}),
            "component_returns": dict(self.component_returns or {}),
            "correlation_matrix": dict(self.correlation_matrix or {}),
            "basket_to_portfolio_corr": self.basket_to_portfolio_corr,
            "data_coverage": dict(self.data_coverage or {}),
            "warnings": list(self.warnings or []),
            "analysis_date": self.analysis_date.isoformat(),
            "summary": self.get_summary(),
            "agent_snapshot": self.get_agent_snapshot(),
        }
        return make_json_safe(payload)
