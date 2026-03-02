"""Realized Performance result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from ._helpers import _convert_to_json_serializable, _clean_nan_values

@dataclass
class RealizedIncomeMetrics:
    """Income breakdown for realized performance analysis."""

    total: float
    dividends: float
    interest: float
    by_month: Dict[str, Any]
    by_symbol: Dict[str, Any]
    by_institution: Dict[str, Any]
    current_monthly_rate: float
    projected_annual: float
    yield_on_cost: float
    yield_on_value: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "dividends": self.dividends,
            "interest": self.interest,
            "by_month": self.by_month,
            "by_symbol": self.by_symbol,
            "by_institution": self.by_institution,
            "current_monthly_rate": self.current_monthly_rate,
            "projected_annual": self.projected_annual,
            "yield_on_cost": self.yield_on_cost,
            "yield_on_value": self.yield_on_value,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedIncomeMetrics":
        return cls(
            total=d.get("total", 0.0),
            dividends=d.get("dividends", 0.0),
            interest=d.get("interest", 0.0),
            by_month=d.get("by_month", {}),
            by_symbol=d.get("by_symbol", {}),
            by_institution=d.get("by_institution", {}),
            current_monthly_rate=d.get("current_monthly_rate", 0.0),
            projected_annual=d.get("projected_annual", 0.0),
            yield_on_cost=d.get("yield_on_cost", 0.0),
            yield_on_value=d.get("yield_on_value", 0.0),
        )

@dataclass
class RealizedPnlBasis:
    """Methodology labels for each P&L track."""

    nav: str
    nav_observed_only: str
    lot: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "nav": self.nav,
            "nav_observed_only": self.nav_observed_only,
            "lot": self.lot,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedPnlBasis":
        return cls(
            nav=d.get("nav", "nav_flow_synthetic_enhanced"),
            nav_observed_only=d.get("nav_observed_only", "nav_flow_observed_only"),
            lot=d.get("lot", "fifo_observed_lots"),
        )

@dataclass
class RealizedMetadata:
    """
    Realized performance metadata: P&L tracks, income, data quality, synthetic positions.

    This is the typed equivalent of the ``realized_metadata`` nested dict returned by
    ``analyze_realized_performance()``.

    Contract semantics:
    - ``nav_pnl_*`` fields represent NAV/flow-derived tracks.
    - ``lot_pnl_usd`` is FIFO lot-based realized+unrealized+income composition.
    - ``provider_flow_coverage`` and ``flow_fallback_reasons`` explain when
      provider-authoritative flow replay was used vs inferred fallback flows.
    """

    realized_pnl: float
    unrealized_pnl: float
    net_contributions: float
    nav_pnl_usd: Optional[float]
    nav_pnl_synthetic_enhanced_usd: Optional[float]
    nav_pnl_observed_only_usd: Optional[float]
    nav_pnl_synthetic_impact_usd: Optional[float]
    lot_pnl_usd: float
    reconciliation_gap_usd: Optional[float]
    pnl_basis: RealizedPnlBasis
    nav_metrics_estimated: bool
    high_confidence_realized: bool
    income: RealizedIncomeMetrics
    data_coverage: float
    inception_date: str
    synthetic_positions: List[Dict[str, str]]
    synthetic_entry_count: int
    synthetic_current_position_count: int
    synthetic_current_position_tickers: List[str]
    synthetic_current_market_value: float
    synthetic_incomplete_trade_count: int
    first_transaction_exit_count: int
    first_transaction_exit_details: List[Any]
    extreme_return_months: List[Any]
    data_quality_flags: List[Dict[str, Any]]
    unpriceable_symbol_count: int
    unpriceable_symbols: List[str]
    unpriceable_reason_counts: Dict[str, int]
    unpriceable_reasons: Dict[str, str]
    ibkr_pricing_coverage: Dict[str, Any]
    source_breakdown: Dict[str, int]
    reliable: bool = False
    reliability_reasons: List[str] = field(default_factory=list)
    holdings_scope: str = "consolidated"
    source_holding_symbols: List[str] = field(default_factory=list)
    source_holding_count: int = 0
    source_transaction_count: int = 0
    cross_source_holding_leakage_symbols: List[str] = field(default_factory=list)
    reliability_reason_codes: List[str] = field(default_factory=list)
    fetch_errors: Dict[str, str] = field(default_factory=dict)
    flow_source_breakdown: Dict[str, int] = field(default_factory=dict)
    inferred_flow_diagnostics: Dict[str, Any] = field(default_factory=dict)
    provider_flow_coverage: Dict[str, Any] = field(default_factory=dict)
    flow_fallback_reasons: List[str] = field(default_factory=list)
    dedup_diagnostics: Dict[str, Any] = field(default_factory=dict)
    external_net_flows_usd: float = 0.0
    net_contributions_definition: str = "trade_cash_legs_legacy"
    data_warnings: List[str] = field(default_factory=list)
    futures_cash_policy: str = "fee_only"
    futures_txn_count_replayed: int = 0
    futures_notional_suppressed_usd: float = 0.0
    futures_fee_cash_impact_usd: float = 0.0
    futures_unknown_action_count: int = 0
    futures_missing_fx_count: int = 0
    income_flow_overlap_dropped_count: int = 0
    income_flow_overlap_dropped_net_usd: float = 0.0
    income_flow_overlap_dropped_by_provider: Dict[str, int] = field(default_factory=dict)
    income_flow_overlap_candidate_count: int = 0
    income_flow_overlap_alias_mismatch_count: int = 0
    income_flow_overlap_alias_mismatch_samples: List[Dict[str, str]] = field(default_factory=list)
    monthly_nav: Optional[Dict[str, float]] = None
    growth_of_dollar: Optional[Dict[str, float]] = None
    _postfilter: Optional[Dict[str, Any]] = None
    account_aggregation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "net_contributions": self.net_contributions,
            "nav_pnl_usd": self.nav_pnl_usd,
            "nav_pnl_synthetic_enhanced_usd": self.nav_pnl_synthetic_enhanced_usd,
            "nav_pnl_observed_only_usd": self.nav_pnl_observed_only_usd,
            "nav_pnl_synthetic_impact_usd": self.nav_pnl_synthetic_impact_usd,
            "lot_pnl_usd": self.lot_pnl_usd,
            "reconciliation_gap_usd": self.reconciliation_gap_usd,
            "pnl_basis": self.pnl_basis.to_dict(),
            "nav_metrics_estimated": self.nav_metrics_estimated,
            "high_confidence_realized": self.high_confidence_realized,
            "income": self.income.to_dict(),
            "data_coverage": self.data_coverage,
            "inception_date": self.inception_date,
            "synthetic_positions": self.synthetic_positions,
            "synthetic_entry_count": self.synthetic_entry_count,
            "synthetic_current_position_count": self.synthetic_current_position_count,
            "synthetic_current_position_tickers": self.synthetic_current_position_tickers,
            "synthetic_current_market_value": self.synthetic_current_market_value,
            "synthetic_incomplete_trade_count": self.synthetic_incomplete_trade_count,
            "first_transaction_exit_count": self.first_transaction_exit_count,
            "first_transaction_exit_details": self.first_transaction_exit_details,
            "extreme_return_months": self.extreme_return_months,
            "data_quality_flags": self.data_quality_flags,
            "unpriceable_symbol_count": self.unpriceable_symbol_count,
            "unpriceable_symbols": self.unpriceable_symbols,
            "unpriceable_reason_counts": self.unpriceable_reason_counts,
            "unpriceable_reasons": self.unpriceable_reasons,
            "ibkr_pricing_coverage": self.ibkr_pricing_coverage,
            "source_breakdown": self.source_breakdown,
            "reliable": self.reliable,
            "reliability_reasons": self.reliability_reasons,
            "holdings_scope": self.holdings_scope,
            "source_holding_symbols": self.source_holding_symbols,
            "source_holding_count": self.source_holding_count,
            "source_transaction_count": self.source_transaction_count,
            "cross_source_holding_leakage_symbols": self.cross_source_holding_leakage_symbols,
            "reliability_reason_codes": self.reliability_reason_codes,
            "fetch_errors": self.fetch_errors,
            "flow_source_breakdown": self.flow_source_breakdown,
            "inferred_flow_diagnostics": self.inferred_flow_diagnostics,
            "provider_flow_coverage": self.provider_flow_coverage,
            "flow_fallback_reasons": self.flow_fallback_reasons,
            "dedup_diagnostics": self.dedup_diagnostics,
            "external_net_flows_usd": self.external_net_flows_usd,
            "net_contributions_definition": self.net_contributions_definition,
            "data_warnings": self.data_warnings,
            "futures_cash_policy": self.futures_cash_policy,
            "futures_txn_count_replayed": self.futures_txn_count_replayed,
            "futures_notional_suppressed_usd": self.futures_notional_suppressed_usd,
            "futures_fee_cash_impact_usd": self.futures_fee_cash_impact_usd,
            "futures_unknown_action_count": self.futures_unknown_action_count,
            "futures_missing_fx_count": self.futures_missing_fx_count,
            "income_flow_overlap_dropped_count": self.income_flow_overlap_dropped_count,
            "income_flow_overlap_dropped_net_usd": self.income_flow_overlap_dropped_net_usd,
            "income_flow_overlap_dropped_by_provider": self.income_flow_overlap_dropped_by_provider,
            "income_flow_overlap_candidate_count": self.income_flow_overlap_candidate_count,
            "income_flow_overlap_alias_mismatch_count": self.income_flow_overlap_alias_mismatch_count,
            "income_flow_overlap_alias_mismatch_samples": self.income_flow_overlap_alias_mismatch_samples,
        }
        if self.monthly_nav is not None:
            d["monthly_nav"] = self.monthly_nav
        if self.growth_of_dollar is not None:
            d["growth_of_dollar"] = self.growth_of_dollar
        if self._postfilter is not None:
            d["_postfilter"] = self._postfilter
        if self.account_aggregation is not None:
            d["account_aggregation"] = self.account_aggregation
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedMetadata":
        return cls(
            realized_pnl=d.get("realized_pnl", 0.0),
            unrealized_pnl=d.get("unrealized_pnl", 0.0),
            net_contributions=d.get("net_contributions", 0.0),
            nav_pnl_usd=d.get("nav_pnl_usd"),
            nav_pnl_synthetic_enhanced_usd=d.get("nav_pnl_synthetic_enhanced_usd"),
            nav_pnl_observed_only_usd=d.get("nav_pnl_observed_only_usd"),
            nav_pnl_synthetic_impact_usd=d.get("nav_pnl_synthetic_impact_usd"),
            lot_pnl_usd=d.get("lot_pnl_usd", 0.0),
            reconciliation_gap_usd=d.get("reconciliation_gap_usd"),
            pnl_basis=RealizedPnlBasis.from_dict(d.get("pnl_basis", {})),
            nav_metrics_estimated=d.get("nav_metrics_estimated", False),
            high_confidence_realized=d.get("high_confidence_realized", False),
            income=RealizedIncomeMetrics.from_dict(d.get("income", {})),
            data_coverage=d.get("data_coverage", 0.0),
            inception_date=d.get("inception_date", ""),
            synthetic_positions=d.get("synthetic_positions", []),
            synthetic_entry_count=d.get("synthetic_entry_count", 0),
            synthetic_current_position_count=d.get("synthetic_current_position_count", 0),
            synthetic_current_position_tickers=d.get("synthetic_current_position_tickers", []),
            synthetic_current_market_value=d.get("synthetic_current_market_value", 0.0),
            synthetic_incomplete_trade_count=d.get("synthetic_incomplete_trade_count", 0),
            first_transaction_exit_count=d.get("first_transaction_exit_count", 0),
            first_transaction_exit_details=d.get("first_transaction_exit_details", []),
            extreme_return_months=d.get("extreme_return_months", []),
            data_quality_flags=d.get("data_quality_flags", []),
            unpriceable_symbol_count=d.get("unpriceable_symbol_count", 0),
            unpriceable_symbols=d.get("unpriceable_symbols", []),
            unpriceable_reason_counts=d.get("unpriceable_reason_counts", {}),
            unpriceable_reasons=d.get("unpriceable_reasons", {}),
            ibkr_pricing_coverage=d.get("ibkr_pricing_coverage", {}),
            source_breakdown=d.get("source_breakdown", {}),
            reliable=bool(d.get("reliable", d.get("high_confidence_realized", False))),
            reliability_reasons=list(d.get("reliability_reasons", [])),
            holdings_scope=str(d.get("holdings_scope", "consolidated") or "consolidated"),
            source_holding_symbols=list(d.get("source_holding_symbols", [])),
            source_holding_count=int(d.get("source_holding_count", len(d.get("source_holding_symbols", []))) or 0),
            source_transaction_count=int(
                d.get(
                    "source_transaction_count",
                    sum(int(v) for v in (d.get("source_breakdown", {}) or {}).values()),
                ) or 0
            ),
            cross_source_holding_leakage_symbols=list(d.get("cross_source_holding_leakage_symbols", [])),
            reliability_reason_codes=list(d.get("reliability_reason_codes", [])),
            fetch_errors=d.get("fetch_errors", {}),
            flow_source_breakdown=d.get("flow_source_breakdown", {}),
            inferred_flow_diagnostics=d.get("inferred_flow_diagnostics", {}),
            provider_flow_coverage=d.get("provider_flow_coverage", {}),
            flow_fallback_reasons=d.get("flow_fallback_reasons", []),
            dedup_diagnostics=d.get("dedup_diagnostics", {}),
            external_net_flows_usd=d.get("external_net_flows_usd", 0.0),
            net_contributions_definition=d.get("net_contributions_definition", "trade_cash_legs_legacy"),
            data_warnings=d.get("data_warnings", []),
            futures_cash_policy=str(d.get("futures_cash_policy", "fee_only") or "fee_only"),
            futures_txn_count_replayed=int(d.get("futures_txn_count_replayed", 0) or 0),
            futures_notional_suppressed_usd=float(d.get("futures_notional_suppressed_usd", 0.0) or 0.0),
            futures_fee_cash_impact_usd=float(d.get("futures_fee_cash_impact_usd", 0.0) or 0.0),
            futures_unknown_action_count=int(d.get("futures_unknown_action_count", 0) or 0),
            futures_missing_fx_count=int(d.get("futures_missing_fx_count", 0) or 0),
            income_flow_overlap_dropped_count=int(d.get("income_flow_overlap_dropped_count", 0) or 0),
            income_flow_overlap_dropped_net_usd=float(d.get("income_flow_overlap_dropped_net_usd", 0.0) or 0.0),
            income_flow_overlap_dropped_by_provider={
                str(k): int(v or 0)
                for k, v in (d.get("income_flow_overlap_dropped_by_provider", {}) or {}).items()
            },
            income_flow_overlap_candidate_count=int(d.get("income_flow_overlap_candidate_count", 0) or 0),
            income_flow_overlap_alias_mismatch_count=int(d.get("income_flow_overlap_alias_mismatch_count", 0) or 0),
            income_flow_overlap_alias_mismatch_samples=[
                dict(item)
                for item in (d.get("income_flow_overlap_alias_mismatch_samples", []) or [])
                if isinstance(item, dict)
            ],
            monthly_nav=d.get("monthly_nav"),
            growth_of_dollar=d.get("growth_of_dollar"),
            _postfilter=d.get("_postfilter"),
            account_aggregation=d.get("account_aggregation"),
        )

@dataclass
class RealizedPerformanceResult:
    """
    Typed result object for realized performance analysis.

    Mirrors the ``PerformanceResult`` pattern for the hypothetical path.
    Core metric fields (returns, risk_metrics, etc.) come from the shared
    ``compute_performance_metrics()`` engine. Realized-specific data lives
    in ``realized_metadata``.

    Called by:
    - Realized performance service/API boundaries that wrap raw analysis dicts.

    Contract:
    - ``to_dict`` preserves the historical realized-performance payload shape.
    - ``to_api_response`` emits the standardized envelope for API/AI clients.
    """

    analysis_period: Dict[str, Any]
    returns: Dict[str, float]
    risk_metrics: Dict[str, float]
    risk_adjusted_returns: Dict[str, float]
    benchmark_analysis: Dict[str, Any]
    benchmark_comparison: Dict[str, float]
    monthly_stats: Dict[str, float]
    risk_free_rate: float
    monthly_returns: Dict[str, float]
    realized_metadata: RealizedMetadata
    warnings: Optional[List[str]] = None
    custom_window: Optional[Dict[str, Any]] = None

    @classmethod
    def from_analysis_dict(cls, d: Dict[str, Any]) -> "RealizedPerformanceResult":
        """Build from the raw dict returned by analyze_realized_performance()."""
        meta_raw = d.get("realized_metadata", {})
        return cls(
            analysis_period=d.get("analysis_period", {}),
            returns=d.get("returns", {}),
            risk_metrics=d.get("risk_metrics", {}),
            risk_adjusted_returns=d.get("risk_adjusted_returns", {}),
            benchmark_analysis=d.get("benchmark_analysis", {}),
            benchmark_comparison=d.get("benchmark_comparison", {}),
            monthly_stats=d.get("monthly_stats", {}),
            risk_free_rate=d.get("risk_free_rate", 0.0),
            monthly_returns=d.get("monthly_returns", {}),
            realized_metadata=RealizedMetadata.from_dict(meta_raw),
            warnings=d.get("warnings"),
            custom_window=d.get("custom_window"),
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedPerformanceResult":
        """Alias for from_analysis_dict() for consistency with other result objects."""
        return cls.from_analysis_dict(d)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the historical realized-performance dict shape."""
        meta_dict = self.realized_metadata.to_dict()
        income = self.realized_metadata.income

        d: Dict[str, Any] = {
            "analysis_period": self.analysis_period,
            "returns": self.returns,
            "risk_metrics": self.risk_metrics,
            "risk_adjusted_returns": self.risk_adjusted_returns,
            "benchmark_analysis": self.benchmark_analysis,
            "benchmark_comparison": self.benchmark_comparison,
            "monthly_stats": self.monthly_stats,
            "risk_free_rate": self.risk_free_rate,
            "monthly_returns": self.monthly_returns,
            "realized_metadata": meta_dict,
            "realized_pnl": self.realized_metadata.realized_pnl,
            "unrealized_pnl": self.realized_metadata.unrealized_pnl,
            "income_total": income.total,
            "income_yield_on_cost": income.yield_on_cost,
            "income_yield_on_value": income.yield_on_value,
            "data_coverage": self.realized_metadata.data_coverage,
            "inception_date": self.realized_metadata.inception_date,
            "nav_pnl_usd": self.realized_metadata.nav_pnl_usd,
            "nav_pnl_observed_only_usd": self.realized_metadata.nav_pnl_observed_only_usd,
            "nav_pnl_synthetic_impact_usd": self.realized_metadata.nav_pnl_synthetic_impact_usd,
            "lot_pnl_usd": self.realized_metadata.lot_pnl_usd,
            "reconciliation_gap_usd": self.realized_metadata.reconciliation_gap_usd,
            "nav_metrics_estimated": self.realized_metadata.nav_metrics_estimated,
            "high_confidence_realized": self.realized_metadata.high_confidence_realized,
            "pnl_basis": self.realized_metadata.pnl_basis.to_dict(),
            "external_net_flows_usd": self.realized_metadata.external_net_flows_usd,
            "net_contributions_definition": self.realized_metadata.net_contributions_definition,
        }
        if self.warnings:
            d["warnings"] = self.warnings
        if self.custom_window is not None:
            d["custom_window"] = self.custom_window
        return d

    def _categorize_performance(self) -> str:
        """Categorize performance based on risk-adjusted metrics."""
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
        annual_return = self.returns.get("annualized_return")
        if sharpe is None or annual_return is None:
            return "unknown"
        if sharpe >= 1.5 and annual_return >= 15:
            return "excellent"
        if sharpe >= 1.0 and annual_return >= 10:
            return "good"
        if sharpe >= 0.5 and annual_return >= 5:
            return "fair"
        return "poor"

    def get_agent_snapshot(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
        """Compact metrics payload for agent-oriented realized performance responses."""
        meta = self.realized_metadata
        income = meta.income
        returns = self.returns or {}
        risk = self.risk_metrics or {}
        risk_adjusted = self.risk_adjusted_returns or {}
        benchmark = self.benchmark_analysis or {}
        benchmark_comp = self.benchmark_comparison or {}
        period = self.analysis_period or {}

        years = period.get("years")
        rounded_years = (
            round(float(years), 1)
            if isinstance(years, numbers.Real) and not isinstance(years, bool)
            else 0.0
        )

        snapshot: Dict[str, Any] = {
            "mode": "realized",
            "period": {
                "start_date": period.get("start_date"),
                "end_date": period.get("end_date"),
                "months": period.get("total_months"),
                "years": rounded_years,
                "inception_date": meta.inception_date,
            },
            "returns": {
                "total_return_pct": returns.get("total_return"),
                "annualized_return_pct": returns.get("annualized_return"),
                "best_month_pct": returns.get("best_month"),
                "worst_month_pct": returns.get("worst_month"),
                "win_rate_pct": returns.get("win_rate"),
            },
            "risk": {
                "volatility_pct": risk.get("volatility"),
                "max_drawdown_pct": risk.get("maximum_drawdown"),
                "sharpe_ratio": risk_adjusted.get("sharpe_ratio"),
                "sortino_ratio": risk_adjusted.get("sortino_ratio"),
            },
            "benchmark": {
                "ticker": benchmark.get("benchmark_ticker", benchmark_ticker),
                "alpha_annual_pct": benchmark.get("alpha_annual"),
                "beta": benchmark.get("beta"),
                "portfolio_return_pct": benchmark_comp.get("portfolio_total_return"),
                "benchmark_return_pct": benchmark_comp.get("benchmark_total_return"),
                "excess_return_pct": benchmark.get("excess_return"),
            },
            "pnl": {
                "nav_pnl_usd": meta.nav_pnl_usd,
                "realized_pnl": meta.realized_pnl,
                "unrealized_pnl": meta.unrealized_pnl,
            },
            "income": {
                "total": income.total if income else None,
                "dividends": income.dividends if income else None,
                "interest": income.interest if income else None,
                "yield_on_cost_pct": income.yield_on_cost if income else None,
                "yield_on_value_pct": income.yield_on_value if income else None,
            },
            "data_quality": {
                "coverage_pct": meta.data_coverage,
                "high_confidence": meta.high_confidence_realized,
                "reliable": meta.reliable,
                "reliability_reasons": list(meta.reliability_reasons or []),
                "reliability_reason_codes": list(meta.reliability_reason_codes or []),
                "synthetic_impact_usd": meta.nav_pnl_synthetic_impact_usd,
                "holdings_scope": meta.holdings_scope,
                "source_transaction_count": meta.source_transaction_count,
                "source_holding_count": meta.source_holding_count,
                "cross_source_holding_leakage_count": len(meta.cross_source_holding_leakage_symbols or []),
                "nav_metrics_estimated": meta.nav_metrics_estimated,
                "synthetic_count": meta.synthetic_current_position_count or 0,
                "warning_count": len(meta.data_warnings or []),
                "futures_cash_policy": meta.futures_cash_policy,
                "futures_txn_count_replayed": meta.futures_txn_count_replayed,
                "futures_notional_suppressed_usd": meta.futures_notional_suppressed_usd,
                "futures_fee_cash_impact_usd": meta.futures_fee_cash_impact_usd,
                "futures_unknown_action_count": meta.futures_unknown_action_count,
                "futures_missing_fx_count": meta.futures_missing_fx_count,
                "income_flow_overlap_dropped_count": meta.income_flow_overlap_dropped_count,
                "income_flow_overlap_dropped_net_usd": meta.income_flow_overlap_dropped_net_usd,
                "income_flow_overlap_dropped_by_provider": dict(meta.income_flow_overlap_dropped_by_provider or {}),
                "income_flow_overlap_candidate_count": meta.income_flow_overlap_candidate_count,
            },
            "verdict": self._categorize_performance(),
            "insights": self._generate_key_insights(),
        }

        if self.custom_window:
            snapshot["custom_window"] = {
                "start_date": self.custom_window.get("start_date"),
                "end_date": self.custom_window.get("end_date"),
                "full_inception": self.custom_window.get("full_inception"),
                "note": self.custom_window.get("note"),
            }

        return make_json_safe(snapshot)

    def _generate_key_insights(self) -> List[str]:
        """Generate key insights bullets based on performance metrics."""
        insights: List[str] = []
        if not bool(self.realized_metadata.reliable):
            reason_codes = list(self.realized_metadata.reliability_reason_codes or [])
            if reason_codes:
                preview = ", ".join(reason_codes[:3])
                if len(reason_codes) > 3:
                    preview = f"{preview}, ..."
            else:
                preview = "low confidence inputs"
            insights.append(
                f"• Reliability warning: realized metrics are low confidence ({preview})"
            )
        alpha = self.benchmark_analysis.get("alpha_annual")
        if alpha is not None and alpha > 5:
            insights.append(f"• Strong alpha generation (+{alpha:.1f}% vs benchmark)")
        elif alpha is not None and alpha < -2:
            insights.append(f"• Underperforming benchmark ({alpha:.1f}% alpha)")
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
        if sharpe is not None and sharpe > 1.2:
            insights.append(f"• Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
        elif sharpe is not None and sharpe < 0.5:
            insights.append(f"• Poor risk-adjusted returns (Sharpe: {sharpe:.2f})")
        volatility = self.risk_metrics.get("volatility")
        benchmark_vol = self.benchmark_comparison.get("benchmark_volatility")
        if (
            volatility is not None
            and benchmark_vol is not None
            and benchmark_vol > 0
            and volatility > benchmark_vol * 1.2
        ):
            insights.append(f"• High volatility ({volatility:.1f}% vs {benchmark_vol:.1f}% benchmark)")
        win_rate = self.returns.get("win_rate")
        if win_rate is not None and win_rate > 65:
            insights.append(f"• High consistency ({win_rate:.0f}% positive months)")
        elif win_rate is not None and win_rate < 50:
            insights.append(f"• Low consistency ({win_rate:.0f}% positive months)")
        max_dd = self.risk_metrics.get("maximum_drawdown")
        if max_dd is not None and abs(max_dd) > 25:
            insights.append(f"• Significant drawdown risk (max: {max_dd:.1f}%)")
        return insights

    def to_summary(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
        """Build the summary-format response dict."""
        meta = self.realized_metadata
        income = meta.income
        benchmark = self.benchmark_analysis

        return {
            "status": "success",
            "mode": "realized",
            "start_date": self.analysis_period.get("start_date"),
            "end_date": self.analysis_period.get("end_date"),
            "total_return": self.returns.get("total_return"),
            "cagr": self.returns.get("annualized_return"),
            "annualized_return": self.returns.get("annualized_return"),
            "volatility": self.risk_metrics.get("volatility"),
            "sharpe_ratio": self.risk_adjusted_returns.get("sharpe_ratio"),
            "max_drawdown": self.risk_metrics.get("maximum_drawdown"),
            "win_rate": self.returns.get("win_rate"),
            "analysis_years": self.analysis_period.get("years", 0),
            "benchmark_ticker": benchmark.get("benchmark_ticker", benchmark_ticker),
            "alpha_annual": benchmark.get("alpha_annual"),
            "beta": benchmark.get("beta"),
            "realized_pnl": meta.realized_pnl,
            "unrealized_pnl": meta.unrealized_pnl,
            "income_total": income.total,
            "income_dividends": income.dividends,
            "income_interest": income.interest,
            "income_by_institution": income.by_institution,
            "income_yield_on_cost": income.yield_on_cost,
            "income_yield_on_value": income.yield_on_value,
            "data_coverage": meta.data_coverage,
            "inception_date": meta.inception_date,
            "synthetic_current_position_count": meta.synthetic_current_position_count,
            "synthetic_current_market_value": meta.synthetic_current_market_value,
            "nav_pnl_usd": meta.nav_pnl_usd,
            "lot_pnl_usd": meta.lot_pnl_usd,
            "reconciliation_gap_usd": meta.reconciliation_gap_usd,
            "nav_metrics_estimated": meta.nav_metrics_estimated,
            "high_confidence_realized": meta.high_confidence_realized,
            "reliable": meta.reliable,
            "reliability_reasons": meta.reliability_reasons,
            "reliability_reason_codes": meta.reliability_reason_codes,
            "pnl_basis": meta.pnl_basis.to_dict(),
            "data_warnings": meta.data_warnings,
            "custom_window": self.custom_window,
            "performance_category": self._categorize_performance(),
            "key_insights": self._generate_key_insights(),
        }

    def to_api_response(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
        """Full API response for realized performance output."""
        del benchmark_ticker
        response = self.to_dict()
        response.get("realized_metadata", {}).pop("_postfilter", None)
        response["status"] = "success"
        response["mode"] = "realized"
        response["performance_category"] = self._categorize_performance()
        response["key_insights"] = self._generate_key_insights()
        return response
