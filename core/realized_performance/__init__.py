from __future__ import annotations

from . import _helpers, aggregation, backfill, engine, fx, holdings, mwr, nav, pricing, provider_flows, timeline
from ._helpers import *
from .aggregation import *
from .backfill import *
from .engine import *
from .fx import *
from .holdings import *
from .mwr import *
from .nav import *
from .pricing import *
from .provider_flows import *
from .timeline import *
from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics
from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from portfolio_risk_engine.factor_utils import calc_monthly_returns
from ibkr.compat import (
    fetch_ibkr_bond_monthly_close,
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
    get_ibkr_futures_fmp_map,
)
from providers.flows.extractor import extract_provider_flow_events
from providers.normalizers.schwab import get_schwab_security_lookup
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
    REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
    REALIZED_PROVIDER_FLOW_SOURCES,
    REALIZED_USE_PROVIDER_FLOWS,
    TRANSACTION_STORE_MAX_AGE_HOURS,
    TRANSACTION_STORE_READ,
    TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES,
)
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source
from trading_analysis.fifo_matcher import FIFOMatcher

REALIZED_CASH_ANCHOR_NAV = True

_helpers._capture_original_sentinels(
    fx.get_monthly_fx_series,
    nav.compute_monthly_returns,
)
_ORIGINAL_GET_MONTHLY_FX_SERIES = _helpers._ORIGINAL_GET_MONTHLY_FX_SERIES
_ORIGINAL_COMPUTE_MONTHLY_RETURNS = _helpers._ORIGINAL_COMPUTE_MONTHLY_RETURNS

__all__ = [
    "_helpers",
    "pricing",
    "holdings",
    "mwr",
    "fx",
    "timeline",
    "nav",
    "provider_flows",
    "backfill",
    "engine",
    "aggregation",
    "compute_performance_metrics",
    "fetch_monthly_close",
    "fetch_monthly_treasury_rates",
    "calc_monthly_returns",
    "extract_provider_flow_events",
    "fetch_ibkr_bond_monthly_close",
    "fetch_ibkr_fx_monthly_close",
    "fetch_ibkr_monthly_close",
    "fetch_ibkr_option_monthly_mark",
    "get_ibkr_futures_fmp_map",
    "get_schwab_security_lookup",
    "BACKFILL_FILE_PATH",
    "DATA_QUALITY_THRESHOLDS",
    "REALIZED_CASH_ANCHOR_NAV",
    "REALIZED_COVERAGE_TARGET",
    "REALIZED_MAX_INCOMPLETE_TRADES",
    "REALIZED_MAX_RECONCILIATION_GAP_PCT",
    "REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE",
    "REALIZED_PROVIDER_FLOW_SOURCES",
    "REALIZED_USE_PROVIDER_FLOWS",
    "TRANSACTION_STORE_MAX_AGE_HOURS",
    "TRANSACTION_STORE_READ",
    "TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES",
    "TradingAnalyzer",
    "fetch_transactions_for_source",
    "FIFOMatcher",
]

for _mod_all in (
    _helpers.__all__,
    pricing.__all__,
    holdings.__all__,
    mwr.__all__,
    fx.__all__,
    timeline.__all__,
    nav.__all__,
    provider_flows.__all__,
    backfill.__all__,
    engine.__all__,
    aggregation.__all__,
):
    for _name in _mod_all:
        if _name not in __all__:
            __all__.append(_name)

del _mod_all
