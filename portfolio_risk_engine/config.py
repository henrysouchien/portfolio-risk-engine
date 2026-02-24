"""Standalone-safe configuration surface for portfolio_risk_engine."""

from __future__ import annotations

import os
from typing import Any


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


_DEFAULTS: dict[str, Any] = {
    "PORTFOLIO_DEFAULTS": {
        "start_date": os.getenv("PORTFOLIO_DEFAULT_START_DATE", "2019-01-31"),
        "end_date": os.getenv("PORTFOLIO_DEFAULT_END_DATE", "2026-01-29"),
        "normalize_weights": os.getenv("PORTFOLIO_DEFAULT_NORMALIZE_WEIGHTS", "false").lower() == "true",
        "worst_case_lookback_years": _env_int("PORTFOLIO_WORST_CASE_LOOKBACK_YEARS", 10),
        "expected_returns_lookback_years": _env_int("PORTFOLIO_EXPECTED_RETURNS_LOOKBACK_YEARS", 10),
        "expected_returns_fallback_default": _env_float("PORTFOLIO_EXPECTED_RETURNS_FALLBACK", 0.06),
        "cash_proxy_fallback_return": _env_float("PORTFOLIO_CASH_PROXY_FALLBACK_RETURN", 0.02),
    },
    "DIVIDEND_DEFAULTS": {
        "lookback_months": _env_int("DIVIDEND_LOOKBACK_MONTHS", 12),
        "min_dividend_data_coverage": _env_float("DIVIDEND_MIN_DATA_COVERAGE", 0.7),
        "include_zero_yield_positions": os.getenv("DIVIDEND_INCLUDE_ZERO_YIELD_POSITIONS", "true").lower() == "true",
    },
    "RATE_FACTOR_CONFIG": {
        "default_maturities": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],
        "treasury_mapping": {
            "UST2Y": "year2",
            "UST5Y": "year5",
            "UST10Y": "year10",
            "UST30Y": "year30",
        },
        "min_required_maturities": 2,
        "scale": "pp",
        "frequency": "M",
        "eligible_asset_classes": ["bond", "real_estate"],
    },
    "DATA_QUALITY_THRESHOLDS": {
        "min_observations_for_factor_betas": 2,
        "min_observations_for_interest_rate_beta": 6,
        "min_observations_for_peer_validation": 3,
        "min_peer_overlap_observations": 1,
        "min_observations_for_returns_calculation": 2,
        "min_observations_for_regression": 3,
        "min_valid_peers_for_median": 1,
        "max_peer_drop_rate": 0.8,
        "min_observations_for_expected_returns": 11,
        "min_observations_for_capm_regression": 12,
        "min_r2_for_rate_factors": 0.3,
        "max_reasonable_interest_rate_beta": 25,
    },
    "RISK_ANALYSIS_THRESHOLDS": {
        "leverage_warning_threshold": 1.1,
        "risk_score_safe_threshold": 0.8,
        "risk_score_caution_threshold": 1.0,
        "risk_score_danger_threshold": 1.5,
        "risk_score_critical_threshold": 2.0,
        "beta_warning_ratio": 0.75,
        "beta_violation_ratio": 1.0,
        "herfindahl_warning_threshold": 0.15,
        "concentration_warning_ratio": 0.8,
        "volatility_warning_ratio": 0.8,
        "factor_variance_warning_ratio": 0.8,
        "market_variance_warning_ratio": 0.8,
        "variance_contribution_threshold": 0.05,
        "industry_concentration_warning_ratio": 0.5,
        "leverage_display_threshold": 1.01,
    },
    "WORST_CASE_SCENARIOS": {
        "market_crash": 0.35,
        "momentum_crash": 0.50,
        "value_crash": 0.40,
        "single_stock_crash": 0.80,
        "sector_crash": 0.50,
        "etf_crash": 0.35,
        "fund_crash": 0.40,
        "mutual_fund_crash": 0.40,
        "cash_crash": 0.05,
        "max_reasonable_volatility": 0.40,
    },
    "MAX_SINGLE_FACTOR_LOSS": {
        "default": -0.10,
        "sector": -0.08,
        "portfolio": -0.08,
    },
    "SECURITY_TYPE_CRASH_MAPPING": {
        "equity": "single_stock_crash",
        "etf": "etf_crash",
        "fund": "fund_crash",
        "mutual_fund": "mutual_fund_crash",
        "cash": "cash_crash",
    },
    "DIVIDEND_LRU_SIZE": _env_int("DIVIDEND_LRU_SIZE", 100),
    "DIVIDEND_DATA_QUALITY_THRESHOLD": _env_float("DIVIDEND_DATA_QUALITY_THRESHOLD", 0.25),
    "PORTFOLIO_RISK_LRU_SIZE": _env_int("PORTFOLIO_RISK_LRU_SIZE", 100),
    "FMP_API_KEY": os.getenv("FMP_API_KEY", ""),
}


try:  # pragma: no cover - monorepo defaults
    import settings as _settings  # type: ignore

    for key in list(_DEFAULTS.keys()):
        if hasattr(_settings, key):
            _DEFAULTS[key] = getattr(_settings, key)
except Exception:
    pass


PORTFOLIO_DEFAULTS = _DEFAULTS["PORTFOLIO_DEFAULTS"]
DIVIDEND_DEFAULTS = _DEFAULTS["DIVIDEND_DEFAULTS"]
RATE_FACTOR_CONFIG = _DEFAULTS["RATE_FACTOR_CONFIG"]
DATA_QUALITY_THRESHOLDS = _DEFAULTS["DATA_QUALITY_THRESHOLDS"]
RISK_ANALYSIS_THRESHOLDS = _DEFAULTS["RISK_ANALYSIS_THRESHOLDS"]
WORST_CASE_SCENARIOS = _DEFAULTS["WORST_CASE_SCENARIOS"]
MAX_SINGLE_FACTOR_LOSS = _DEFAULTS["MAX_SINGLE_FACTOR_LOSS"]
SECURITY_TYPE_CRASH_MAPPING = _DEFAULTS["SECURITY_TYPE_CRASH_MAPPING"]
DIVIDEND_LRU_SIZE = int(_DEFAULTS["DIVIDEND_LRU_SIZE"])
DIVIDEND_DATA_QUALITY_THRESHOLD = float(_DEFAULTS["DIVIDEND_DATA_QUALITY_THRESHOLD"])
PORTFOLIO_RISK_LRU_SIZE = int(_DEFAULTS["PORTFOLIO_RISK_LRU_SIZE"])
FMP_API_KEY = str(_DEFAULTS["FMP_API_KEY"])


def configure(**overrides: Any) -> None:
    """Programmatically override package configuration values."""
    globals_dict = globals()
    for key, value in overrides.items():
        if key not in globals_dict:
            raise KeyError(f"Unknown config key: {key}")
        globals_dict[key] = value
