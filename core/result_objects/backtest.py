"""Backtest result object."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from utils.serialization import make_json_safe


@dataclass
class BacktestResult:
    """Structured backtest output with API + agent helpers."""

    performance_metrics: Dict[str, Any]
    monthly_returns: Dict[str, float]
    benchmark_monthly_returns: Dict[str, float]
    cumulative_returns: Dict[str, float]
    benchmark_cumulative: Dict[str, float]
    annual_breakdown: List[Dict[str, Any]]
    weights: Dict[str, float]
    benchmark_ticker: str
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    portfolio_name: Optional[str] = None
    excluded_tickers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @classmethod
    def from_core_backtest(
        cls,
        backtest_data: Dict[str, Any],
        *,
        portfolio_name: Optional[str] = None,
        analysis_date: Optional[datetime] = None,
    ) -> "BacktestResult":
        """Build BacktestResult from ``backtest_engine.run_backtest()`` output."""
        return cls(
            performance_metrics=backtest_data.get("performance_metrics", {}),
            monthly_returns=backtest_data.get("monthly_returns", {}),
            benchmark_monthly_returns=backtest_data.get("benchmark_monthly_returns", {}),
            cumulative_returns=backtest_data.get("cumulative_returns", {}),
            benchmark_cumulative=backtest_data.get("benchmark_cumulative", {}),
            annual_breakdown=backtest_data.get("annual_breakdown", []),
            weights=backtest_data.get("weights", {}),
            benchmark_ticker=backtest_data.get("benchmark_ticker", "SPY"),
            analysis_date=analysis_date or datetime.now(UTC),
            portfolio_name=portfolio_name,
            excluded_tickers=backtest_data.get("excluded_tickers", []) or [],
            warnings=backtest_data.get("warnings", []) or [],
        )

    def get_summary(self) -> Dict[str, Any]:
        """Return compact summary metrics for API and MCP wrappers."""
        returns = self.performance_metrics.get("returns", {})
        benchmark = self.performance_metrics.get("benchmark_comparison", {})
        risk = self.performance_metrics.get("risk_metrics", {})
        risk_adjusted = self.performance_metrics.get("risk_adjusted_returns", {})
        period = self.performance_metrics.get("analysis_period", {})

        portfolio_total = benchmark.get("portfolio_total_return", returns.get("total_return", 0))
        benchmark_total = benchmark.get("benchmark_total_return", 0)
        alpha_total = (
            round(float(portfolio_total) - float(benchmark_total), 2)
            if portfolio_total is not None and benchmark_total is not None
            else None
        )

        return make_json_safe(
            {
                "benchmark_ticker": self.benchmark_ticker,
                "total_return": returns.get("total_return", 0),
                "benchmark_total_return": benchmark_total,
                "alpha_total": alpha_total,
                "annualized_return": returns.get("annualized_return", 0),
                "sharpe_ratio": risk_adjusted.get("sharpe_ratio", 0),
                "max_drawdown": risk.get("maximum_drawdown", 0),
                "analysis_months": period.get("total_months", 0),
                "analysis_years": period.get("years", 0),
                "excluded_ticker_count": len(self.excluded_tickers),
                "warning_count": len(self.warnings),
            }
        )

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Return compact payload for flag generation and agent reasoning."""
        period = self.performance_metrics.get("analysis_period", {})
        returns = self.performance_metrics.get("returns", {})
        benchmark = self.performance_metrics.get("benchmark_comparison", {})
        risk = self.performance_metrics.get("risk_metrics", {})
        risk_adjusted = self.performance_metrics.get("risk_adjusted_returns", {})
        annual_alpha_values: list[float] = []

        for row in self.annual_breakdown:
            if not isinstance(row, dict):
                continue
            try:
                alpha = float(row.get("alpha"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(alpha):
                annual_alpha_values.append(alpha)

        portfolio_total = benchmark.get("portfolio_total_return", returns.get("total_return"))
        benchmark_total = benchmark.get("benchmark_total_return")
        excess = (
            round(float(portfolio_total) - float(benchmark_total), 2)
            if portfolio_total is not None and benchmark_total is not None
            else None
        )
        annual_alpha_positive_count = sum(1 for alpha in annual_alpha_values if alpha > 0)
        annual_alpha_total = len(annual_alpha_values)

        return make_json_safe(
            {
                "mode": "backtest",
                "period": {
                    "start_date": period.get("start_date"),
                    "end_date": period.get("end_date"),
                    "months": period.get("total_months"),
                    "years": period.get("years"),
                },
                "benchmark": {"ticker": self.benchmark_ticker},
                "returns": {
                    "portfolio_total_return_pct": portfolio_total,
                    "benchmark_total_return_pct": benchmark_total,
                    "excess_return_pct": excess,
                },
                "risk": {
                    "max_drawdown_pct": risk.get("maximum_drawdown"),
                    "sharpe_ratio": risk_adjusted.get("sharpe_ratio"),
                },
                "volatility": risk.get("volatility"),
                "sortino_ratio": risk_adjusted.get("sortino_ratio"),
                "down_capture_ratio": risk_adjusted.get("down_capture_ratio"),
                "annual_alpha_positive_count": annual_alpha_positive_count,
                "annual_alpha_total": annual_alpha_total,
                "data_quality": {
                    "excluded_tickers": self.excluded_tickers,
                    "excluded_count": len(self.excluded_tickers),
                    "warning_count": len(self.warnings),
                },
                "warnings": self.warnings,
                "resolved_weights": {k: round(v, 6) for k, v in self.weights.items()},
            }
        )

    def to_api_response(self) -> Dict[str, Any]:
        """Serialize for API consumers."""
        return make_json_safe(
            {
                "performance_metrics": self.performance_metrics,
                "monthly_returns": self.monthly_returns,
                "benchmark_monthly_returns": self.benchmark_monthly_returns,
                "cumulative_returns": self.cumulative_returns,
                "benchmark_cumulative": self.benchmark_cumulative,
                "annual_breakdown": self.annual_breakdown,
                "weights": self.weights,
                "benchmark_ticker": self.benchmark_ticker,
                "excluded_tickers": self.excluded_tickers,
                "warnings": self.warnings,
                "analysis_date": self.analysis_date.isoformat(),
                "portfolio_name": self.portfolio_name,
            }
        )
