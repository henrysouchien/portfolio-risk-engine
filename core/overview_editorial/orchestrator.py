"""Data gathering for the Overview editorial pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

from core.cash_helpers import is_cash_ticker
from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.editorial_state_store import load_editorial_state
from services.events_service import get_portfolio_events_snapshot
from services.income_helpers import build_income_snapshot
from services.performance_helpers import apply_date_window, load_portfolio_for_performance
from services.portfolio_context import load_portfolio_for_analysis
from services.portfolio.result_cache import (
    get_analysis_result_snapshot,
    get_events_result_snapshot,
    get_income_projection_result_snapshot,
    get_performance_result_snapshot,
    get_realized_performance_result_snapshot,
)
from services.portfolio.workflow_cache import get_factor_proxies_snapshot, get_risk_limits_snapshot
from services.portfolio_service import PortfolioService
from services.position_service import PositionService
from services.tax_harvest_service import get_tax_harvest_snapshot_for_overview
from services.trading_service import get_trading_snapshot_for_overview

_logger = logging.getLogger(__name__)
_DEFAULT_PORTFOLIO_NAME = "CURRENT_PORTFOLIO"


def _normalize_portfolio_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or _DEFAULT_PORTFOLIO_NAME


def _safe_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None
    return None


def _fraction_from_percentish(value: Any) -> float | None:
    number = _safe_number(value)
    if number is None:
        return None
    return number / 100.0 if abs(number) > 1.0 else number


def _percent_from_fractionish(value: Any) -> float | None:
    number = _safe_number(value)
    if number is None:
        return None
    return number * 100.0 if abs(number) <= 1.0 else number


def _normalized_float_dict(value: Any, *, fraction_values: bool = False) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        number = _fraction_from_percentish(raw_value) if fraction_values else _safe_number(raw_value)
        if number is None:
            continue
        normalized[key] = number
    return normalized


def _is_valid_cost_basis(value: Any) -> bool:
    number = _safe_number(value)
    return number is not None and number != 0.0


def _position_weight_pct(value: Any, total_value: float) -> float:
    number = _safe_number(value)
    if number is None or not total_value:
        return 0.0
    return round((abs(number) / abs(total_value)) * 100.0, 1)


def _normalized_loss_positions_from_monitor_payload(result: Any, *, total_value: float) -> list[dict[str, Any]]:
    builder = getattr(result, "_build_monitor_payload", None)
    if not callable(builder):
        return []

    try:
        payload = builder()
    except Exception:
        return []

    normalized: list[dict[str, Any]] = []
    for position in list(payload.get("positions") or []):
        if not isinstance(position, dict):
            continue

        ticker = str(position.get("ticker") or "").strip().upper()
        if not ticker or is_cash_ticker(ticker) or bool(position.get("is_cash_equivalent")):
            continue

        pnl_dollar = _safe_number(position.get("dollar_pnl"))
        if pnl_dollar is None:
            pnl_dollar = _safe_number(position.get("pnl"))
        if pnl_dollar is None or pnl_dollar >= 0:
            continue

        value = _safe_number(position.get("net_exposure"))
        if value is None:
            value = _safe_number(position.get("gross_exposure"))

        cost_basis = _safe_number(position.get("cost_basis_usd"))
        if cost_basis is None:
            cost_basis = _safe_number(position.get("cost_basis"))

        normalized.append(
            {
                "ticker": ticker,
                "value": value,
                "cost_basis": cost_basis,
                "weight_pct": _position_weight_pct(value, total_value),
                "pnl_dollar": pnl_dollar,
                "pnl_usd": _safe_number(position.get("pnl_usd")) or pnl_dollar,
                "pnl_pct": _safe_number(position.get("pnl_percent")),
            }
        )

    normalized.sort(
        key=lambda item: (
            _safe_number(item.get("pnl_usd")) if _safe_number(item.get("pnl_usd")) is not None else _safe_number(item.get("pnl_dollar")) or 0.0,
            str(item.get("ticker") or ""),
        )
    )
    return normalized[:10]


def _fallback_normalized_loss_positions(all_positions: list[dict[str, Any]], *, total_value: float) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for position in all_positions:
        if not isinstance(position, dict):
            continue

        ticker = str(position.get("ticker") or "").strip().upper()
        position_type = str(position.get("type") or "").strip().lower()
        if not ticker or position_type == "cash" or is_cash_ticker(ticker) or bool(position.get("is_cash_equivalent")):
            continue

        value = _safe_number(position.get("value"))
        cost_basis = _safe_number(position.get("cost_basis_usd"))
        if cost_basis is None:
            cost_basis = _safe_number(position.get("cost_basis"))
        if not _is_valid_cost_basis(cost_basis):
            continue

        pnl_dollar = _safe_number(position.get("dollar_pnl"))
        if pnl_dollar is None:
            pnl_dollar = _safe_number(position.get("pnl"))
        pnl_pct = _safe_number(position.get("pnl_percent"))
        pnl_usd = _safe_number(position.get("pnl_usd"))

        quantity = _safe_number(position.get("quantity"))
        raw_price = _safe_number(position.get("local_price"))
        if raw_price is None:
            raw_price = _safe_number(position.get("price"))
        if raw_price is None and quantity not in (None, 0) and value is not None:
            raw_price = value / quantity

        if pnl_dollar is None and quantity not in (None, 0) and raw_price is not None:
            entry_price = abs(float(cost_basis)) / abs(float(quantity))
            pnl_dollar = (raw_price - entry_price) * quantity
        if pnl_usd is None:
            pnl_usd = pnl_dollar
        if pnl_pct is None and pnl_dollar is not None and _is_valid_cost_basis(cost_basis):
            pnl_pct = (pnl_dollar / abs(float(cost_basis))) * 100.0
        if pnl_dollar is None or pnl_dollar >= 0:
            continue

        normalized.append(
            {
                "ticker": ticker,
                "value": value,
                "cost_basis": cost_basis,
                "weight_pct": _position_weight_pct(value, total_value),
                "pnl_dollar": pnl_dollar,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
            }
        )

    normalized.sort(
        key=lambda item: (
            _safe_number(item.get("pnl_usd")) if _safe_number(item.get("pnl_usd")) is not None else _safe_number(item.get("pnl_dollar")) or 0.0,
            str(item.get("ticker") or ""),
        )
    )
    return normalized[:10]


def _normalize_positions(result: Any) -> dict[str, Any]:
    holdings = list(getattr(result, "get_top_holdings", lambda _n=10: [])(10) or [])
    all_positions = list(getattr(getattr(result, "data", None), "positions", []) or [])
    total_value = _safe_number(getattr(result, "total_value", 0.0)) or 0.0
    weight_terms = []
    all_tickers_with_weights: dict[str, float] = {}
    if total_value:
        for position in all_positions:
            ticker = str(position.get("ticker") or "").strip().upper()
            position_type = str(position.get("type") or "").strip().lower()
            value = _safe_number(position.get("value"))
            if value is None:
                continue
            weight_terms.append((abs(value) / abs(total_value)) ** 2)
            if not ticker or position_type == "cash" or is_cash_ticker(ticker) or bool(position.get("is_cash_equivalent")):
                continue
            all_tickers_with_weights[ticker] = _position_weight_pct(value, total_value)

    loss_positions = _normalized_loss_positions_from_monitor_payload(result, total_value=total_value)
    if not loss_positions:
        loss_positions = _fallback_normalized_loss_positions(all_positions, total_value=total_value)

    return {
        "snapshot": {
            "holdings": holdings,
            "total_value": total_value,
            "hhi": round(sum(weight_terms), 6) if weight_terms else 0.0,
            "position_count": len(all_positions),
            "loss_positions": loss_positions,
            "all_tickers_with_weights": all_tickers_with_weights,
        },
        "flags": [],
    }


def _normalize_risk(result: Any) -> dict[str, Any]:
    summary = getattr(result, "get_summary", lambda: {})() or {}
    agent_snapshot = getattr(result, "get_agent_snapshot", lambda: {})() or {}
    variance_decomposition = agent_snapshot.get("variance_decomposition") or {}
    if not isinstance(variance_decomposition, dict):
        variance_decomposition = {}
    variance_decomposition = {
        **variance_decomposition,
        "factor_pct": _fraction_from_percentish(variance_decomposition.get("factor_pct")),
        "idiosyncratic_pct": _fraction_from_percentish(variance_decomposition.get("idiosyncratic_pct")),
        "factor_breakdown_pct": _normalized_float_dict(
            variance_decomposition.get("factor_breakdown_pct"),
            fraction_values=True,
        ),
    }
    return {
        "snapshot": {
            "volatility_annual": summary.get("volatility_annual"),
            "herfindahl": summary.get("herfindahl"),
            "risk_drivers": summary.get("risk_drivers", []),
            "leverage": summary.get("leverage"),
            "factor_variance_pct": _percent_from_fractionish(
                variance_decomposition.get("factor_pct", summary.get("factor_variance_pct"))
            ),
            "risk_limit_violations": agent_snapshot.get("risk_limit_violations_summary", []),
            "portfolio_factor_betas": _normalized_float_dict(agent_snapshot.get("portfolio_factor_betas")),
            "variance_decomposition": variance_decomposition,
            "beta_exposure_checks_table": list(agent_snapshot.get("beta_exposure_checks_table") or []),
        },
        "flags": [],
    }


def _derive_factor_from_risk(risk_tool_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(risk_tool_result, dict):
        return {"snapshot": {}, "flags": []}

    snapshot = risk_tool_result.get("snapshot")
    if not isinstance(snapshot, dict):
        return {"snapshot": {}, "flags": list(risk_tool_result.get("flags") or [])}

    factor_betas = _normalized_float_dict(snapshot.get("portfolio_factor_betas"))
    factor_variance_pct = _percent_from_fractionish(snapshot.get("factor_variance_pct"))
    variance_decomposition = snapshot.get("variance_decomposition") or {}
    if not isinstance(variance_decomposition, dict):
        variance_decomposition = {}
    factor_breakdown_pct = _normalized_float_dict(
        variance_decomposition.get("factor_breakdown_pct"),
        fraction_values=True,
    )

    dominant_factor = None
    dominant_factor_pct = None
    if factor_breakdown_pct:
        dominant_factor, dominant_fraction = max(
            factor_breakdown_pct.items(),
            key=lambda item: abs(item[1]),
        )
        dominant_factor_pct = round(abs(dominant_fraction) * 100.0, 1)

    beta_exposure_violations: list[dict[str, Any]] = []
    for row in list(snapshot.get("beta_exposure_checks_table") or []):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().upper()
        portfolio_beta = _safe_number(row.get("portfolio_beta"))
        max_allowed_beta = _safe_number(row.get("max_allowed_beta"))
        is_violation = status == "FAIL"
        if not is_violation and portfolio_beta is not None and max_allowed_beta is not None:
            is_violation = abs(portfolio_beta) > abs(max_allowed_beta)
        if not is_violation:
            continue
        beta_exposure_violations.append(
            {
                "factor": str(row.get("factor") or "").strip().lower(),
                "portfolio_beta": portfolio_beta,
                "max_allowed_beta": max_allowed_beta,
                "status": status or "FAIL",
                "formatted_line": row.get("formatted_line"),
            }
        )

    concentration_score = round(sum(abs(value) ** 2 for value in factor_breakdown_pct.values()), 4)
    if not any(
        [
            factor_betas,
            factor_breakdown_pct,
            factor_variance_pct is not None,
            beta_exposure_violations,
        ]
    ):
        return {"snapshot": {}, "flags": list(risk_tool_result.get("flags") or [])}

    return {
        "snapshot": {
            "portfolio_factor_betas": factor_betas,
            "factor_variance_pct": factor_variance_pct,
            "factor_breakdown_pct": factor_breakdown_pct,
            "dominant_factor": dominant_factor,
            "dominant_factor_pct": dominant_factor_pct,
            "factor_concentration_score": concentration_score,
            "beta_exposure_violations": beta_exposure_violations,
        },
        "flags": list(risk_tool_result.get("flags") or []),
    }


def _get_agent_snapshot(result: Any, *, benchmark_ticker: str) -> dict[str, Any]:
    getter = getattr(result, "get_agent_snapshot", None)
    if not callable(getter):
        return {}
    try:
        snapshot = getter(benchmark_ticker=benchmark_ticker)
    except TypeError:
        snapshot = getter()
    return snapshot if isinstance(snapshot, dict) else {}


def _performance_sections(agent_snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    returns = agent_snapshot.get("returns", {}) if isinstance(agent_snapshot, dict) else {}
    risk = agent_snapshot.get("risk", {}) if isinstance(agent_snapshot, dict) else {}
    benchmark = agent_snapshot.get("benchmark", {}) if isinstance(agent_snapshot, dict) else {}
    return returns, risk, benchmark


def _resolve_benchmark_ticker(agent_snapshot: dict[str, Any], *, benchmark_ticker: str) -> str:
    _, _, benchmark = _performance_sections(agent_snapshot)
    resolved = benchmark.get("ticker") or benchmark.get("benchmark_ticker") or benchmark_ticker
    return str(resolved or benchmark_ticker)


def _extract_total_return_pct(result: Any, *, benchmark_ticker: str) -> float | None:
    snapshot = _get_agent_snapshot(result, benchmark_ticker=benchmark_ticker)
    returns, _, _ = _performance_sections(snapshot)
    return _safe_number(returns.get("total_return_pct"))


def _extract_benchmark_return_pct(result: Any, *, benchmark_ticker: str) -> float | None:
    snapshot = _get_agent_snapshot(result, benchmark_ticker=benchmark_ticker)
    _, _, benchmark = _performance_sections(snapshot)
    return _safe_number(benchmark.get("benchmark_return_pct"))


def _coerce_realized_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    from core.result_objects import RealizedPerformanceResult

    return RealizedPerformanceResult.from_analysis_dict(result)


def _normalize_performance(
    result: Any,
    *,
    benchmark_ticker: str,
    display_return_pct: float | None = None,
    display_return_label: str | None = None,
    display_benchmark_return_pct: float | None = None,
) -> dict[str, Any]:
    agent_snapshot = _get_agent_snapshot(result, benchmark_ticker=benchmark_ticker)
    returns, risk, benchmark = _performance_sections(agent_snapshot)
    resolved_benchmark_ticker = _resolve_benchmark_ticker(agent_snapshot, benchmark_ticker=benchmark_ticker)

    return {
        "snapshot": {
            "display_return_pct": display_return_pct if display_return_pct is not None else returns.get("total_return_pct"),
            "return_context_label": display_return_label or f"vs {resolved_benchmark_ticker}",
            "mode": agent_snapshot.get("mode"),
            "total_return_pct": returns.get("total_return_pct"),
            "annualized_return_pct": returns.get("annualized_return_pct"),
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
            "sharpe_ratio": risk.get("sharpe_ratio"),
            "alpha_annual_pct": benchmark.get("alpha_annual_pct"),
            "beta": benchmark.get("beta"),
            "benchmark_return_pct": (
                display_benchmark_return_pct
                if display_benchmark_return_pct is not None
                else benchmark.get("benchmark_return_pct")
            ),
            "benchmark_sharpe": benchmark.get("sharpe_ratio"),
            "benchmark_ticker": resolved_benchmark_ticker,
        },
        "flags": [],
    }


def _normalize_events(result: Any) -> dict[str, Any]:
    events = list(result.get("events") or []) if isinstance(result, dict) else []
    normalized: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        ticker = str(event.get("ticker") or "").strip().upper()
        event_type = str(event.get("event_type") or "").strip().lower()
        event_date = str(event.get("date") or "").strip()
        if not ticker or not event_type or not event_date:
            continue
        normalized.append(
            {
                "ticker": ticker,
                "event_type": event_type,
                "date": event_date,
                "days_until": int(event.get("days_until") or 0),
                "weight_pct": float(event.get("weight_pct") or 0.0),
            }
        )
    return {"snapshot": {"events": normalized, "event_count": len(normalized)}, "flags": []}


def _normalize_income(result: Any) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {"status": "error", "error": "invalid income payload"}
    return {"snapshot": build_income_snapshot(payload), "flags": []}


class DataGatheringOrchestrator:
    """Parallel fan-out for the current user's Overview editorial context."""

    def __init__(
        self,
        *,
        position_service_cls: type[PositionService] = PositionService,
        portfolio_service_cls: type[PortfolioService] = PortfolioService,
        load_portfolio_for_analysis_fn=load_portfolio_for_analysis,
        load_portfolio_for_performance_fn=load_portfolio_for_performance,
        get_analysis_result_snapshot_fn=get_analysis_result_snapshot,
        get_events_result_snapshot_fn=get_events_result_snapshot,
        get_income_projection_result_snapshot_fn=get_income_projection_result_snapshot,
        get_performance_result_snapshot_fn=get_performance_result_snapshot,
        get_realized_performance_result_snapshot_fn=get_realized_performance_result_snapshot,
        get_factor_proxies_snapshot_fn=get_factor_proxies_snapshot,
        get_risk_limits_snapshot_fn=get_risk_limits_snapshot,
        get_tax_harvest_snapshot_for_overview_fn=get_tax_harvest_snapshot_for_overview,
        get_trading_snapshot_for_overview_fn=get_trading_snapshot_for_overview,
        load_editorial_state_fn=load_editorial_state,
        apply_date_window_fn=apply_date_window,
        events_service_fn=get_portfolio_events_snapshot,
        income_projection_data_fn=None,
        tax_harvest_data_fn=None,
        trading_snapshot_fn=None,
        now_fn=lambda: datetime.now(UTC),
    ) -> None:
        self._position_service_cls = position_service_cls
        self._portfolio_service_cls = portfolio_service_cls
        self._load_portfolio_for_analysis = load_portfolio_for_analysis_fn
        self._load_portfolio_for_performance = load_portfolio_for_performance_fn
        self._get_analysis_result_snapshot = get_analysis_result_snapshot_fn
        self._get_events_result_snapshot = get_events_result_snapshot_fn
        self._get_income_projection_result_snapshot = get_income_projection_result_snapshot_fn
        self._get_performance_result_snapshot = get_performance_result_snapshot_fn
        self._get_realized_performance_result_snapshot = get_realized_performance_result_snapshot_fn
        self._get_factor_proxies_snapshot = get_factor_proxies_snapshot_fn
        self._get_risk_limits_snapshot = get_risk_limits_snapshot_fn
        self._get_tax_harvest_snapshot_for_overview = get_tax_harvest_snapshot_for_overview_fn
        self._get_trading_snapshot_for_overview = get_trading_snapshot_for_overview_fn
        self._load_editorial_state = load_editorial_state_fn
        self._apply_date_window = apply_date_window_fn
        self._events_service = events_service_fn
        self._income_projection_data = income_projection_data_fn
        self._tax_harvest_data = tax_harvest_data_fn
        self._trading_snapshot = trading_snapshot_fn
        self._now = now_fn

    def _build_income_projection(
        self,
        *,
        user_email: str,
        portfolio_name: str,
        use_cache: bool,
    ) -> dict[str, Any]:
        if self._income_projection_data is not None:
            return self._income_projection_data(
                user_email=user_email,
                portfolio_name=portfolio_name,
                projection_months=12,
                use_cache=use_cache,
            )

        from actions.income_projection import get_income_projection_data

        return get_income_projection_data(
            user_email=user_email,
            portfolio_name=portfolio_name,
            projection_months=12,
            use_cache=use_cache,
        )

    def _build_tax_harvest(
        self,
        *,
        user_email: str,
        portfolio_name: str,
        use_cache: bool,
    ) -> dict[str, Any]:
        if self._tax_harvest_data is not None:
            return self._tax_harvest_data(
                user_email=user_email,
                portfolio_name=portfolio_name,
                use_cache=use_cache,
            )

        from mcp_tools.tax_harvest import suggest_tax_loss_harvest

        return suggest_tax_loss_harvest(
            user_email=user_email,
            portfolio_name=portfolio_name,
            format="summary",
            use_cache=use_cache,
        )

    def _build_trading_snapshot(
        self,
        *,
        user_email: str,
        portfolio_name: str,
    ) -> dict[str, Any]:
        if self._trading_snapshot is not None:
            return self._trading_snapshot(
                user_email=user_email,
                portfolio_name=portfolio_name,
            )

        return self._get_trading_snapshot_for_overview(
            user_email=user_email,
            portfolio_name=portfolio_name,
        )

    def _current_overview_dates(self) -> tuple[str, str, str]:
        today = self._now().date()
        return (
            date(today.year, 1, 1).isoformat(),
            (today - timedelta(days=365)).isoformat(),
            today.isoformat(),
        )

    def _current_events_window(self) -> tuple[str, str]:
        today = self._now().date()
        return today.isoformat(), (today + timedelta(days=30)).isoformat()

    def _load_hypothetical_performance_portfolio(
        self,
        *,
        user_email: str,
        portfolio_name: str,
        start_date: str,
        end_date: str,
        use_cache: bool,
    ) -> Any:
        _, _, portfolio_data, _ = self._load_portfolio_for_performance(
            user_email=user_email,
            portfolio_name=portfolio_name,
            use_cache=use_cache,
            start_date=start_date,
            end_date=end_date,
            mode="hypothetical",
        )
        return portfolio_data

    def _build_hypothetical_overview_performance(
        self,
        *,
        user_email: str,
        user_id: int,
        portfolio_name: str,
        benchmark_ticker: str,
        use_cache: bool,
    ) -> dict[str, Any]:
        ytd_start, one_year_start, today = self._current_overview_dates()
        portfolio_service = self._portfolio_service_cls(cache_results=use_cache)

        canonical_portfolio_data = self._load_hypothetical_performance_portfolio(
            user_email=user_email,
            portfolio_name=portfolio_name,
            start_date=one_year_start,
            end_date=today,
            use_cache=use_cache,
        )
        canonical_result = self._get_performance_result_snapshot(
            user_id=user_id,
            portfolio_name=portfolio_name,
            portfolio_data=canonical_portfolio_data,
            benchmark_ticker=benchmark_ticker,
            cache_scope="overview_1y_summary",
            builder=lambda: portfolio_service.analyze_performance(
                canonical_portfolio_data,
                benchmark_ticker=benchmark_ticker,
                include_attribution=False,
                include_optional_metrics=False,
            ),
            use_cache=use_cache,
        )
        ytd_return_pct: float | None = None
        ytd_benchmark_return_pct: float | None = None
        if ytd_start == one_year_start:
            ytd_return_pct = _extract_total_return_pct(canonical_result, benchmark_ticker=benchmark_ticker)
            ytd_benchmark_return_pct = _extract_benchmark_return_pct(canonical_result, benchmark_ticker=benchmark_ticker)
        else:
            ytd_portfolio_data = self._load_hypothetical_performance_portfolio(
                user_email=user_email,
                portfolio_name=portfolio_name,
                start_date=ytd_start,
                end_date=today,
                use_cache=use_cache,
            )
            ytd_result = self._get_performance_result_snapshot(
                user_id=user_id,
                portfolio_name=portfolio_name,
                portfolio_data=ytd_portfolio_data,
                benchmark_ticker=benchmark_ticker,
                cache_scope="overview_ytd_summary",
                builder=lambda: portfolio_service.analyze_performance(
                    ytd_portfolio_data,
                    benchmark_ticker=benchmark_ticker,
                    include_attribution=False,
                    include_optional_metrics=False,
                ),
                use_cache=use_cache,
            )
            ytd_return_pct = _extract_total_return_pct(ytd_result, benchmark_ticker=benchmark_ticker)
            ytd_benchmark_return_pct = _extract_benchmark_return_pct(ytd_result, benchmark_ticker=benchmark_ticker)

        resolved_benchmark_ticker = _resolve_benchmark_ticker(
            _get_agent_snapshot(canonical_result, benchmark_ticker=benchmark_ticker),
            benchmark_ticker=benchmark_ticker,
        )
        label = f"YTD vs {resolved_benchmark_ticker}" if ytd_return_pct is not None else f"vs {resolved_benchmark_ticker}"
        return _normalize_performance(
            canonical_result,
            benchmark_ticker=benchmark_ticker,
            display_return_pct=ytd_return_pct,
            display_return_label=label,
            display_benchmark_return_pct=ytd_benchmark_return_pct,
        )

    def _build_realized_overview_performance(
        self,
        *,
        user_email: str,
        user_id: int,
        portfolio_name: str,
        benchmark_ticker: str,
        use_cache: bool,
    ) -> dict[str, Any] | None:
        ytd_start, _, today = self._current_overview_dates()

        try:
            _, _, portfolio_data, position_result = self._load_portfolio_for_performance(
                user_email=user_email,
                portfolio_name=portfolio_name,
                use_cache=use_cache,
                mode="realized",
            )
            portfolio_service = self._portfolio_service_cls(cache_results=use_cache)
            realized_result = self._get_realized_performance_result_snapshot(
                user_id=user_id,
                portfolio_name=portfolio_name,
                portfolio_data=portfolio_data,
                benchmark_ticker=benchmark_ticker,
                source="all",
                institution=None,
                account=None,
                segment="all",
                include_series=False,
                start_date=None,
                builder=lambda: portfolio_service.analyze_realized_performance(
                    position_result=position_result,
                    user_email=user_email,
                    benchmark_ticker=benchmark_ticker,
                    source="all",
                    segment="all",
                    include_series=False,
                ),
                use_cache=use_cache,
            )
            realized_result = _coerce_realized_result(realized_result)
            ytd_result = self._apply_date_window(realized_result, ytd_start, today)
            ytd_result = None if isinstance(ytd_result, dict) else ytd_result
            ytd_return_pct = (
                _extract_total_return_pct(ytd_result, benchmark_ticker=benchmark_ticker)
                if ytd_result is not None
                else None
            )
            ytd_benchmark_return_pct = (
                _extract_benchmark_return_pct(ytd_result, benchmark_ticker=benchmark_ticker)
                if ytd_result is not None
                else None
            )

            resolved_benchmark_ticker = _resolve_benchmark_ticker(
                _get_agent_snapshot(realized_result, benchmark_ticker=benchmark_ticker),
                benchmark_ticker=benchmark_ticker,
            )
            label = f"YTD vs {resolved_benchmark_ticker}" if ytd_return_pct is not None else f"vs {resolved_benchmark_ticker}"
            return _normalize_performance(
                realized_result,
                benchmark_ticker=benchmark_ticker,
                display_return_pct=ytd_return_pct,
                display_return_label=label,
                display_benchmark_return_pct=ytd_benchmark_return_pct,
            )
        except Exception:
            _logger.info(
                "overview realized performance unavailable for user %s portfolio %s",
                user_id,
                portfolio_name,
                exc_info=True,
            )
            return None

    def gather(
        self,
        *,
        user_email: str,
        user_id: int,
        portfolio_id: str | None = None,
        benchmark_ticker: str = "SPY",
        use_cache: bool = True,
    ) -> PortfolioContext:
        normalized_portfolio_name = _normalize_portfolio_name(portfolio_id)
        _, resolved_user_id, portfolio_data = self._load_portfolio_for_analysis(
            user_email,
            normalized_portfolio_name,
            use_cache=use_cache,
        )
        effective_user_id = user_id or resolved_user_id

        try:
            factor_proxies = self._get_factor_proxies_snapshot(
                effective_user_id,
                normalized_portfolio_name,
                portfolio_data,
                allow_gpt=True,
            )
        except Exception:
            factor_proxies = {}
        if factor_proxies:
            portfolio_data.stock_factor_proxies = factor_proxies
            refresh_cache_key = getattr(portfolio_data, "refresh_cache_key", None)
            if callable(refresh_cache_key):
                refresh_cache_key()

        risk_limits_data, _ = self._get_risk_limits_snapshot(effective_user_id, normalized_portfolio_name)
        tool_results: dict[str, dict[str, Any]] = {}
        data_status: dict[str, str] = {}

        def _gather_positions() -> tuple[str, dict[str, Any] | None, str]:
            try:
                service = self._position_service_cls(user_email=user_email, user_id=effective_user_id)
                result = service.get_all_positions(consolidate=True, use_cache=use_cache, force_refresh=not use_cache)
                return "positions", _normalize_positions(result), "loaded"
            except Exception:
                _logger.warning("overview positions gather failed for user %s", effective_user_id, exc_info=True)
                return "positions", None, "failed"

        def _gather_risk() -> tuple[str, dict[str, Any] | None, str]:
            try:
                portfolio_service = self._portfolio_service_cls(cache_results=use_cache)
                result = self._get_analysis_result_snapshot(
                    user_id=effective_user_id,
                    portfolio_name=normalized_portfolio_name,
                    portfolio_data=portfolio_data,
                    risk_limits_data=risk_limits_data,
                    performance_period="1M",
                    builder=lambda: portfolio_service.analyze_portfolio(
                        portfolio_data,
                        risk_limits_data,
                        performance_period="1M",
                    ),
                    use_cache=use_cache,
                )
                return "risk", _normalize_risk(result), "loaded"
            except Exception:
                _logger.warning("overview risk gather failed for user %s", effective_user_id, exc_info=True)
                return "risk", None, "failed"

        def _gather_performance() -> tuple[str, dict[str, Any] | None, str]:
            try:
                realized_snapshot = self._build_realized_overview_performance(
                    user_email=user_email,
                    user_id=effective_user_id,
                    portfolio_name=normalized_portfolio_name,
                    benchmark_ticker=benchmark_ticker,
                    use_cache=use_cache,
                )
                if realized_snapshot is not None:
                    return "performance", realized_snapshot, "loaded"

                hypothetical_snapshot = self._build_hypothetical_overview_performance(
                    user_email=user_email,
                    user_id=effective_user_id,
                    portfolio_name=normalized_portfolio_name,
                    benchmark_ticker=benchmark_ticker,
                    use_cache=use_cache,
                )
                return "performance", hypothetical_snapshot, "loaded"
            except Exception:
                _logger.warning("overview performance gather failed for user %s", effective_user_id, exc_info=True)
                return "performance", None, "failed"

        def _gather_income() -> tuple[str, dict[str, Any] | None, str]:
            try:
                result = self._get_income_projection_result_snapshot(
                    user_id=effective_user_id,
                    portfolio_name=normalized_portfolio_name,
                    projection_months=12,
                    format="summary",
                    builder=lambda: self._build_income_projection(
                        user_email=user_email,
                        portfolio_name=normalized_portfolio_name,
                        use_cache=use_cache,
                    ),
                    use_cache=use_cache,
                )
                return "income", _normalize_income(result), "loaded"
            except Exception:
                _logger.warning("overview income gather failed for user %s", effective_user_id, exc_info=True)
                return "income", None, "failed"

        def _gather_tax_harvest() -> tuple[str, dict[str, Any] | None, str]:
            try:
                snapshot = self._get_tax_harvest_snapshot_for_overview(
                    builder=lambda: self._build_tax_harvest(
                        user_email=user_email,
                        portfolio_name=normalized_portfolio_name,
                        use_cache=use_cache,
                    )
                )
                return "tax", {"snapshot": snapshot, "flags": []}, "loaded"
            except Exception:
                _logger.warning("overview tax harvest gather failed for user %s", effective_user_id, exc_info=True)
                return "tax", None, "failed"

        def _gather_trading() -> tuple[str, dict[str, Any] | None, str]:
            try:
                snapshot = self._build_trading_snapshot(
                    user_email=user_email,
                    portfolio_name=normalized_portfolio_name,
                )
                return "trading", {"snapshot": snapshot, "flags": []}, "loaded"
            except Exception:
                _logger.warning("overview trading gather failed for user %s", effective_user_id, exc_info=True)
                return "trading", None, "failed"

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(_gather_positions),
                executor.submit(_gather_risk),
                executor.submit(_gather_performance),
                executor.submit(_gather_income),
                executor.submit(_gather_tax_harvest),
                executor.submit(_gather_trading),
            ]
            for future in as_completed(futures):
                tool_name, normalized, status = future.result()
                if normalized is not None:
                    tool_results[tool_name] = normalized
                data_status[tool_name] = status

        if data_status.get("risk") == "loaded":
            tool_results["factor"] = _derive_factor_from_risk(tool_results.get("risk"))
            data_status["factor"] = "loaded"
        else:
            data_status["factor"] = "failed"

        def _gather_events() -> tuple[str, dict[str, Any] | None, str]:
            try:
                if data_status.get("positions") == "failed":
                    return "events", None, "failed"
                positions_snapshot = tool_results.get("positions", {}).get("snapshot") or {}
                tickers_with_weights = positions_snapshot.get("all_tickers_with_weights")
                if not isinstance(tickers_with_weights, dict) or not tickers_with_weights:
                    return "events", _normalize_events({"events": []}), "loaded"

                start_date, end_date = self._current_events_window()
                symbols_key = ",".join(sorted(str(ticker).strip().upper() for ticker in tickers_with_weights))
                result = self._get_events_result_snapshot(
                    user_id=effective_user_id,
                    portfolio_name=normalized_portfolio_name,
                    from_date=start_date,
                    to_date=end_date,
                    symbols_key=symbols_key,
                    event_types="earnings,dividends",
                    builder=lambda: self._events_service(
                        tickers_with_weights=tickers_with_weights,
                        start_date=start_date,
                        end_date=end_date,
                        use_cache=use_cache,
                    ),
                    use_cache=use_cache,
                )
                return "events", _normalize_events(result), "loaded"
            except Exception:
                _logger.warning("overview events gather failed for user %s", effective_user_id, exc_info=True)
                return "events", None, "failed"

        event_name, event_normalized, event_status = _gather_events()
        if event_normalized is not None:
            tool_results[event_name] = event_normalized
        data_status[event_name] = event_status

        editorial_memory, previous_brief_anchor = self._load_editorial_state(
            effective_user_id,
            portfolio_id,
        )

        return PortfolioContext(
            user_id=effective_user_id,
            portfolio_id=portfolio_id,
            portfolio_name=normalized_portfolio_name,
            tool_results=tool_results,
            data_status=data_status,
            editorial_memory=editorial_memory,
            previous_brief_anchor=previous_brief_anchor,
            generated_at=datetime.now(UTC),
        )


def gather_portfolio_context(
    user_email: str,
    user_id: int,
    portfolio_id: str | None = None,
    *,
    benchmark_ticker: str = "SPY",
    use_cache: bool = True,
) -> PortfolioContext:
    return DataGatheringOrchestrator().gather(
        user_email=user_email,
        user_id=user_id,
        portfolio_id=portfolio_id,
        benchmark_ticker=benchmark_ticker,
        use_cache=use_cache,
    )
