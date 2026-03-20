from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable, Literal


@dataclass(frozen=True)
class AgentFunction:
    callable: Callable
    tier: Literal["tool", "building_block"]
    read_only: bool
    category: str
    has_user_email: bool


BLOCKED_PARAMS = {
    "backfill_path": None,
    "output": "inline",
    "debug_inference": False,
}

AGENT_FUNCTIONS: dict[str, AgentFunction] = {}


def get_registry() -> dict[str, AgentFunction]:
    if not AGENT_FUNCTIONS:
        _build_registry()
    return AGENT_FUNCTIONS


def _unwrap(fn: Callable) -> Callable:
    """Get the unwrapped function, bypassing @handle_mcp_errors."""
    return getattr(fn, "__wrapped__", fn)


def _register(
    name: str,
    fn: Callable,
    *,
    tier: Literal["tool", "building_block"] = "tool",
    read_only: bool = True,
    category: str = "general",
) -> None:
    unwrapped = _unwrap(fn)
    has_user_email = "user_email" in inspect.signature(unwrapped).parameters
    AGENT_FUNCTIONS[name] = AgentFunction(
        callable=unwrapped,
        tier=tier,
        read_only=read_only,
        category=category,
        has_user_email=has_user_email,
    )


def _build_registry() -> None:
    """Build the lazy Phase 1 allowlist registry."""
    AGENT_FUNCTIONS.clear()

    from mcp_tools.positions import get_positions
    from mcp_tools.risk import (
        get_leverage_capacity,
        get_risk_analysis,
        get_risk_profile,
        get_risk_score,
    )
    from mcp_tools.performance import get_performance
    from mcp_tools.optimization import get_efficient_frontier, run_optimization
    from mcp_tools.whatif import run_whatif
    from mcp_tools.backtest import run_backtest
    from mcp_tools.trading_analysis import get_trading_analysis
    from mcp_tools.income import get_income_projection
    from mcp_tools.tax_harvest import suggest_tax_loss_harvest
    from mcp_tools.transactions import (
        inspect_transactions,
        list_flow_events,
        list_income_events,
        list_ingestion_batches,
        list_transactions,
        transaction_coverage,
    )
    from mcp_tools.hedge_monitor import monitor_hedge_positions
    from mcp_tools.baskets import get_basket, list_baskets
    from mcp_tools.compare import compare_scenarios
    from mcp_tools.factor_intelligence import (
        get_factor_analysis,
        get_factor_recommendations,
    )
    from mcp_tools.rebalance import generate_rebalance_trades
    from mcp_tools.signals import check_exit_signals
    from mcp_tools.trading import get_orders
    from mcp_tools.basket_trading import preview_basket_trade, execute_basket_trade
    from mcp_tools.futures_roll import preview_futures_roll, execute_futures_roll
    from mcp_tools.multi_leg_options import preview_option_trade, execute_option_trade
    from mcp_tools.portfolio_management import (
        account_activate,
        account_deactivate,
        create_portfolio,
        delete_portfolio,
        update_portfolio_accounts,
    )
    from mcp_tools.audit import record_workflow_action, update_action_status
    from mcp_tools.stock import analyze_stock
    from mcp_tools.quote import get_quote
    from mcp_tools.futures_curve import get_futures_curve
    from mcp_tools.chain_analysis import analyze_option_chain
    from mcp_tools.options import analyze_option_strategy
    from mcp_tools.risk import set_risk_profile
    from mcp_tools.baskets import (
        create_basket,
        create_basket_from_etf,
        delete_basket,
        update_basket,
    )
    from mcp_tools.trading import cancel_order, execute_trade, preview_trade
    from mcp_tools.transactions import ingest_transactions, refresh_transactions
    from services.agent_building_blocks import (
        compute_metrics,
        fetch_fmp_data,
        get_correlation_matrix,
        get_dividend_history,
        get_factor_exposures,
        get_portfolio_weights,
        get_price_series,
        get_returns_series,
        run_monte_carlo,
        run_stress_test,
    )

    _register("get_positions", get_positions, category="positions")
    _register("get_risk_score", get_risk_score, category="risk")
    _register("get_risk_analysis", get_risk_analysis, category="risk")
    _register("get_leverage_capacity", get_leverage_capacity, category="risk")
    _register("get_risk_profile", get_risk_profile, category="risk")
    _register("get_performance", get_performance, category="performance")
    _register("run_optimization", run_optimization, category="optimization")
    _register("get_efficient_frontier", get_efficient_frontier, category="optimization")
    _register("run_whatif", run_whatif, category="scenarios")
    _register("run_backtest", run_backtest, category="scenarios")
    _register("get_trading_analysis", get_trading_analysis, category="analysis")
    _register("get_income_projection", get_income_projection, category="income")
    _register("suggest_tax_loss_harvest", suggest_tax_loss_harvest, category="income")
    _register("list_transactions", list_transactions, category="transactions")
    _register("list_ingestion_batches", list_ingestion_batches, category="transactions")
    _register("inspect_transactions", inspect_transactions, category="transactions")
    _register("list_flow_events", list_flow_events, category="transactions")
    _register("list_income_events", list_income_events, category="transactions")
    _register("transaction_coverage", transaction_coverage, category="transactions")
    _register("monitor_hedge_positions", monitor_hedge_positions, category="risk")
    _register("list_baskets", list_baskets, category="baskets")
    _register("get_basket", get_basket, category="baskets")
    _register("compare_scenarios", compare_scenarios, category="scenarios")
    _register("get_factor_analysis", get_factor_analysis, category="analysis")
    _register("get_factor_recommendations", get_factor_recommendations, category="analysis")
    _register("generate_rebalance_trades", generate_rebalance_trades, category="analysis")
    _register("check_exit_signals", check_exit_signals, category="analysis")
    _register("get_orders", get_orders, category="trading")

    _register("analyze_stock", analyze_stock, category="analysis")
    _register("get_quote", get_quote, category="market")
    _register("get_futures_curve", get_futures_curve, category="market")
    _register("analyze_option_chain", analyze_option_chain, category="options")
    _register("analyze_option_strategy", analyze_option_strategy, category="options")

    _register("preview_trade", preview_trade, read_only=False, category="trading")
    _register("execute_trade", execute_trade, read_only=False, category="trading")
    _register("cancel_order", cancel_order, read_only=False, category="trading")
    _register(
        "preview_basket_trade",
        preview_basket_trade,
        read_only=False,
        category="trading",
    )
    _register(
        "execute_basket_trade",
        execute_basket_trade,
        read_only=False,
        category="trading",
    )
    _register(
        "preview_futures_roll",
        preview_futures_roll,
        read_only=False,
        category="trading",
    )
    _register(
        "execute_futures_roll",
        execute_futures_roll,
        read_only=False,
        category="trading",
    )
    _register(
        "preview_option_trade",
        preview_option_trade,
        read_only=False,
        category="trading",
    )
    _register(
        "execute_option_trade",
        execute_option_trade,
        read_only=False,
        category="trading",
    )
    _register(
        "create_portfolio",
        create_portfolio,
        read_only=False,
        category="portfolio_mgmt",
    )
    _register(
        "delete_portfolio",
        delete_portfolio,
        read_only=False,
        category="portfolio_mgmt",
    )
    _register(
        "update_portfolio_accounts",
        update_portfolio_accounts,
        read_only=False,
        category="portfolio_mgmt",
    )
    _register(
        "account_activate",
        account_activate,
        read_only=False,
        category="portfolio_mgmt",
    )
    _register(
        "account_deactivate",
        account_deactivate,
        read_only=False,
        category="portfolio_mgmt",
    )
    _register("set_risk_profile", set_risk_profile, read_only=False, category="risk")
    _register("create_basket", create_basket, read_only=False, category="baskets")
    _register("update_basket", update_basket, read_only=False, category="baskets")
    _register("delete_basket", delete_basket, read_only=False, category="baskets")
    _register(
        "create_basket_from_etf",
        create_basket_from_etf,
        read_only=False,
        category="baskets",
    )
    _register(
        "record_workflow_action",
        record_workflow_action,
        read_only=False,
        category="audit",
    )
    _register(
        "update_action_status",
        update_action_status,
        read_only=False,
        category="audit",
    )
    _register(
        "ingest_transactions",
        ingest_transactions,
        read_only=False,
        category="transactions",
    )
    _register(
        "refresh_transactions",
        refresh_transactions,
        read_only=False,
        category="transactions",
    )

    _register("get_price_series", get_price_series, tier="building_block", category="data")
    _register("get_returns_series", get_returns_series, tier="building_block", category="data")
    _register("get_portfolio_weights", get_portfolio_weights, tier="building_block", category="data")
    _register("get_correlation_matrix", get_correlation_matrix, tier="building_block", category="data")
    _register("compute_metrics", compute_metrics, tier="building_block", category="compute")
    _register("run_stress_test", run_stress_test, tier="building_block", category="compute")
    _register("run_monte_carlo", run_monte_carlo, tier="building_block", category="compute")
    _register("get_factor_exposures", get_factor_exposures, tier="building_block", category="data")
    _register("fetch_fmp_data", fetch_fmp_data, tier="building_block", category="data")
    _register("get_dividend_history", get_dividend_history, tier="building_block", category="data")


__all__ = [
    "AgentFunction",
    "BLOCKED_PARAMS",
    "get_registry",
]
