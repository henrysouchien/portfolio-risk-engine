"""Monte Carlo result object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from utils.serialization import make_json_safe


@dataclass
class MonteCarloResult:
    """Structured Monte Carlo output with API + agent helpers."""

    num_simulations: int
    time_horizon_months: int
    initial_value: float
    percentile_paths: Dict[str, List[float]]
    terminal_distribution: Dict[str, float]
    distribution: str = "normal"
    requested_distribution: str = "normal"
    distribution_fallback_reason: Optional[str] = None
    distribution_params: Dict[str, Any] = field(default_factory=dict)
    vol_scale: float = 1.0
    weights_overridden: bool = False
    resolved_weights: Optional[Dict[str, float]] = None
    bootstrap_sample_size: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    portfolio_name: Optional[str] = None
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_engine_output(
        cls,
        data: dict,
        *,
        portfolio_name: Optional[str] = None,
    ) -> "MonteCarloResult":
        """Build MonteCarloResult from ``monte_carlo.run_monte_carlo()`` output."""
        return cls(
            num_simulations=int(data.get("num_simulations", 0)),
            time_horizon_months=int(data.get("time_horizon_months", 0)),
            initial_value=float(data.get("initial_value", 0.0)),
            percentile_paths=data.get("percentile_paths", {}) or {},
            terminal_distribution=data.get("terminal_distribution", {}) or {},
            distribution=str(data.get("distribution", "normal")),
            requested_distribution=str(data.get("requested_distribution", "normal")),
            distribution_fallback_reason=data.get("distribution_fallback_reason"),
            distribution_params=data.get("distribution_params", {}) or {},
            vol_scale=float(data.get("vol_scale", 1.0)),
            weights_overridden=bool(data.get("weights_overridden", False)),
            resolved_weights=data.get("resolved_weights"),
            bootstrap_sample_size=data.get("bootstrap_sample_size"),
            warnings=list(data.get("warnings", []) or []),
            portfolio_name=portfolio_name,
        )

    def get_summary(self) -> Dict[str, Any]:
        """Return compact summary metrics for API and MCP wrappers."""
        terminal = self.terminal_distribution
        return make_json_safe(
            {
                "num_simulations": self.num_simulations,
                "time_horizon_months": self.time_horizon_months,
                "initial_value": self.initial_value,
                "distribution": self.distribution,
                "requested_distribution": self.requested_distribution,
                "distribution_fallback_reason": self.distribution_fallback_reason,
                "distribution_params": self.distribution_params,
                "vol_scale": self.vol_scale,
                "weights_overridden": self.weights_overridden,
                "resolved_weights": self.resolved_weights,
                "bootstrap_sample_size": self.bootstrap_sample_size,
                "mean_terminal_value": terminal.get("mean", 0.0),
                "median_terminal_value": terminal.get("median", 0.0),
                "p5_terminal_value": terminal.get("p5", 0.0),
                "p95_terminal_value": terminal.get("p95", 0.0),
                "var_95": terminal.get("var_95", 0.0),
                "cvar_95": terminal.get("cvar_95", 0.0),
                "probability_of_loss": terminal.get("probability_of_loss", 0.0),
                "warning_count": len(self.warnings),
                "warnings": self.warnings,
            }
        )

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Return compact payload for flag generation and agent reasoning."""
        terminal = self.terminal_distribution
        return make_json_safe(
            {
                "mode": "monte_carlo",
                "simulation": {
                    "num_simulations": self.num_simulations,
                    "time_horizon_months": self.time_horizon_months,
                    "distribution": self.distribution,
                    "requested_distribution": self.requested_distribution,
                    "distribution_fallback_reason": self.distribution_fallback_reason,
                    "distribution_params": self.distribution_params,
                    "vol_scale": self.vol_scale,
                    "bootstrap_sample_size": self.bootstrap_sample_size,
                },
                "terminal": {
                    "mean": terminal.get("mean", 0.0),
                    "median": terminal.get("median", 0.0),
                    "p5": terminal.get("p5", 0.0),
                    "p95": terminal.get("p95", 0.0),
                    "var_95": terminal.get("var_95", 0.0),
                    "cvar_95": terminal.get("cvar_95", 0.0),
                    "probability_of_loss": terminal.get("probability_of_loss", 0.0),
                    "max_gain_pct": terminal.get("max_gain_pct", 0.0),
                    "max_loss_pct": terminal.get("max_loss_pct", 0.0),
                },
                "initial_value": self.initial_value,
                "conditioning": {
                    "weights_overridden": self.weights_overridden,
                    "resolved_weights": self.resolved_weights,
                    "vol_scale": self.vol_scale,
                },
                "warnings": self.warnings,
            }
        )

    def to_api_response(self) -> Dict[str, Any]:
        """Serialize for API consumers."""
        return make_json_safe(
            {
                "num_simulations": self.num_simulations,
                "time_horizon_months": self.time_horizon_months,
                "initial_value": self.initial_value,
                "percentile_paths": self.percentile_paths,
                "terminal_distribution": self.terminal_distribution,
                "distribution": self.distribution,
                "requested_distribution": self.requested_distribution,
                "distribution_fallback_reason": self.distribution_fallback_reason,
                "distribution_params": self.distribution_params,
                "vol_scale": self.vol_scale,
                "weights_overridden": self.weights_overridden,
                "resolved_weights": self.resolved_weights,
                "bootstrap_sample_size": self.bootstrap_sample_size,
                "warnings": self.warnings,
                "analysis_date": self.analysis_date.isoformat(),
                "portfolio_name": self.portfolio_name,
            }
        )
