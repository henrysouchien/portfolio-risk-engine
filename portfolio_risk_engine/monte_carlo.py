"""Monte Carlo simulation engine for portfolio terminal-value distributions."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.result_objects import RiskAnalysisResult


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        if np.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def _nearest_psd(matrix: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """Project a symmetric matrix onto the PSD cone by clamping eigenvalues."""
    symmetric = (matrix + matrix.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    clamped = np.clip(eigenvalues, epsilon, None)
    psd = (eigenvectors @ np.diag(clamped) @ eigenvectors.T).real
    return (psd + psd.T) / 2.0


def _infer_annual_expected_returns(values: list[float]) -> bool:
    """
    Infer whether expected returns are annualized.

    Heuristic:
    - If magnitudes are typically above 3% per period, treat as annual.
    - Values > 1.5 are interpreted as percentage points and normalized earlier.
    """
    if not values:
        return False
    abs_values = np.abs(np.asarray(values, dtype=float))
    median_abs = float(np.median(abs_values))
    max_abs = float(np.max(abs_values))
    return median_abs > 0.03 or max_abs > 0.20


def _extract_weights(risk_result: RiskAnalysisResult) -> Dict[str, float]:
    portfolio_weights = getattr(risk_result, "portfolio_weights", None)
    if isinstance(portfolio_weights, dict) and portfolio_weights:
        return {
            str(ticker): _safe_float(weight, default=0.0)
            for ticker, weight in portfolio_weights.items()
        }

    allocations = getattr(risk_result, "allocations", None)
    if isinstance(allocations, pd.DataFrame) and "Portfolio Weight" in allocations.columns:
        return {
            str(ticker): _safe_float(weight, default=0.0)
            for ticker, weight in allocations["Portfolio Weight"].to_dict().items()
        }

    return {}


def _resolve_tickers_and_covariance(
    risk_result: RiskAnalysisResult,
    weights: Dict[str, float],
) -> tuple[list[str], np.ndarray]:
    cov_df = getattr(risk_result, "covariance_matrix", None)
    if isinstance(cov_df, pd.DataFrame) and not cov_df.empty:
        numeric_cov = cov_df.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        candidate_tickers = [
            str(ticker)
            for ticker in numeric_cov.index
            if ticker in numeric_cov.columns
        ]
        tickers = [ticker for ticker in candidate_tickers if ticker in weights] or candidate_tickers
        if tickers:
            cov_values = numeric_cov.loc[tickers, tickers].to_numpy(dtype=float)
            cov_values = (cov_values + cov_values.T) / 2.0
            return tickers, cov_values

    tickers = list(weights.keys())
    if not tickers:
        return [], np.zeros((0, 0), dtype=float)

    return tickers, np.zeros((len(tickers), len(tickers)), dtype=float)


def _resolve_weight_vector(
    tickers: list[str],
    raw_weights: Dict[str, float],
) -> np.ndarray:
    if not tickers:
        return np.zeros(0, dtype=float)

    weight_vector = np.asarray(
        [_safe_float(raw_weights.get(ticker), default=0.0) for ticker in tickers],
        dtype=float,
    )

    total = float(np.sum(weight_vector))
    if abs(total) < 1e-12:
        abs_total = float(np.sum(np.abs(weight_vector)))
        if abs_total > 1e-12:
            weight_vector = weight_vector / abs_total
        else:
            weight_vector = np.full(len(tickers), 1.0 / len(tickers), dtype=float)
    else:
        weight_vector = weight_vector / total

    return weight_vector


def _resolve_monthly_drift(
    risk_result: RiskAnalysisResult,
    tickers: list[str],
) -> np.ndarray:
    portfolio_returns = getattr(risk_result, "portfolio_returns", None)
    portfolio_monthly_mean = 0.0
    if isinstance(portfolio_returns, pd.Series) and not portfolio_returns.empty:
        portfolio_monthly_mean = _safe_float(portfolio_returns.mean(), default=0.0)

    expected_returns_raw = getattr(risk_result, "expected_returns", None) or {}
    if not isinstance(expected_returns_raw, dict) or len(expected_returns_raw) == 0:
        return np.full(len(tickers), portfolio_monthly_mean, dtype=float)

    normalized_expected: Dict[str, float] = {}
    for ticker, value in expected_returns_raw.items():
        if not np.isfinite(_safe_float(value, default=np.nan)):
            continue
        expected = float(value)
        # Accept both decimal (0.08) and percentage-point (8.0) styles.
        if abs(expected) > 1.5:
            expected = expected / 100.0
        normalized_expected[str(ticker)] = expected

    inferred_annual = _infer_annual_expected_returns(list(normalized_expected.values()))
    monthly_default = portfolio_monthly_mean

    monthly_drift = []
    for ticker in tickers:
        expected = normalized_expected.get(ticker)
        if expected is None:
            monthly_drift.append(monthly_default)
        else:
            monthly_drift.append(expected / 12.0 if inferred_annual else expected)

    return np.asarray(monthly_drift, dtype=float)


def _build_correlation_transform(covariance: np.ndarray) -> np.ndarray:
    n_assets = covariance.shape[0]
    if n_assets == 0:
        return covariance

    safe_covariance = np.nan_to_num(
        (covariance + covariance.T) / 2.0,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    # Single-asset fallback: use direct monthly variance.
    if n_assets == 1:
        variance = float(np.clip(safe_covariance[0, 0], 0.0, None))
        return np.asarray([[np.sqrt(variance)]], dtype=float)

    # Degenerate covariance (e.g., zero-vol or perfectly collinear assets):
    # use diagonal simulation and avoid injecting artificial variance.
    if np.linalg.matrix_rank(safe_covariance) < n_assets:
        variances = np.clip(np.diag(safe_covariance), 0.0, None)
        return np.diag(np.sqrt(variances))

    try:
        return np.linalg.cholesky(safe_covariance)
    except np.linalg.LinAlgError:
        try:
            # Repair tiny non-PSD numerical noise before decomposing.
            return np.linalg.cholesky(_nearest_psd(safe_covariance))
        except np.linalg.LinAlgError:
            # Singular fallback: independent Gaussian shocks from diagonal variances.
            variances = np.clip(np.diag(safe_covariance), 0.0, None)
            return np.diag(np.sqrt(variances))


def _build_flat_result(
    num_simulations: int,
    time_horizon_months: int,
    initial_value: float,
) -> Dict[str, Any]:
    path = [float(initial_value) for _ in range(time_horizon_months + 1)]
    return {
        "num_simulations": int(num_simulations),
        "time_horizon_months": int(time_horizon_months),
        "initial_value": float(initial_value),
        "percentile_paths": {
            "p5": path.copy(),
            "p25": path.copy(),
            "p50": path.copy(),
            "p75": path.copy(),
            "p95": path.copy(),
        },
        "terminal_distribution": {
            "mean": float(initial_value),
            "median": float(initial_value),
            "min": float(initial_value),
            "max": float(initial_value),
            "p5": float(initial_value),
            "p95": float(initial_value),
            "var_95": 0.0,
            "cvar_95": 0.0,
            "probability_of_loss": 0.0,
            "max_gain_pct": 0.0,
            "max_loss_pct": 0.0,
        },
    }


def run_monte_carlo(
    risk_result: RiskAnalysisResult,
    num_simulations: int = 1000,
    time_horizon_months: int = 12,
    portfolio_value: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run monthly Monte Carlo simulation from RiskAnalysisResult inputs.

    Notes:
    - Uses monthly covariance directly (no annual-to-monthly scaling).
    - Floors asset monthly returns at -99% to avoid impossible <-100% asset moves.
    """
    if num_simulations <= 0:
        raise ValueError("num_simulations must be > 0")
    if time_horizon_months <= 0:
        raise ValueError("time_horizon_months must be > 0")

    initial_value = _safe_float(
        portfolio_value if portfolio_value is not None else getattr(risk_result, "total_value", None),
        default=0.0,
    )
    if initial_value <= 0:
        initial_value = 1.0

    raw_weights = _extract_weights(risk_result)
    tickers, covariance = _resolve_tickers_and_covariance(risk_result, raw_weights)
    if not tickers:
        return _build_flat_result(num_simulations, time_horizon_months, initial_value)

    weight_vector = _resolve_weight_vector(tickers, raw_weights)
    monthly_drift = _resolve_monthly_drift(risk_result, tickers)
    transform = _build_correlation_transform(covariance)

    n_assets = len(tickers)
    rng = np.random.default_rng()
    z = rng.standard_normal(size=(num_simulations, time_horizon_months, n_assets))
    correlated_shocks = z @ transform.T
    monthly_asset_returns = correlated_shocks + monthly_drift.reshape(1, 1, -1)
    monthly_asset_returns = np.clip(monthly_asset_returns, -0.99, None)

    monthly_portfolio_returns = monthly_asset_returns @ weight_vector
    monthly_portfolio_returns = np.clip(monthly_portfolio_returns, -0.99, None)

    growth = 1.0 + monthly_portfolio_returns
    compounded = initial_value * np.cumprod(growth, axis=1)
    paths = np.concatenate(
        [np.full((num_simulations, 1), initial_value, dtype=float), compounded],
        axis=1,
    )

    percentile_levels = [5, 25, 50, 75, 95]
    percentile_matrix = np.percentile(paths, percentile_levels, axis=0)
    percentile_paths = {
        "p5": percentile_matrix[0].astype(float).tolist(),
        "p25": percentile_matrix[1].astype(float).tolist(),
        "p50": percentile_matrix[2].astype(float).tolist(),
        "p75": percentile_matrix[3].astype(float).tolist(),
        "p95": percentile_matrix[4].astype(float).tolist(),
    }

    terminal_values = paths[:, -1]
    terminal_p5 = float(np.percentile(terminal_values, 5))
    var_95 = max(float(initial_value - terminal_p5), 0.0)

    tail_losses = np.maximum(initial_value - terminal_values[terminal_values <= terminal_p5], 0.0)
    cvar_95 = float(np.mean(tail_losses)) if tail_losses.size > 0 else var_95

    terminal_returns_pct = ((terminal_values / initial_value) - 1.0) * 100.0
    terminal_distribution = {
        "mean": float(np.mean(terminal_values)),
        "median": float(np.median(terminal_values)),
        "min": float(np.min(terminal_values)),
        "max": float(np.max(terminal_values)),
        "p5": terminal_p5,
        "p95": float(np.percentile(terminal_values, 95)),
        "var_95": var_95,
        "cvar_95": max(cvar_95, 0.0),
        "probability_of_loss": float(np.mean(terminal_values < initial_value)),
        "max_gain_pct": float(np.max(terminal_returns_pct)),
        "max_loss_pct": float(np.min(terminal_returns_pct)),
    }

    return {
        "num_simulations": int(num_simulations),
        "time_horizon_months": int(time_horizon_months),
        "initial_value": float(initial_value),
        "percentile_paths": percentile_paths,
        "terminal_distribution": terminal_distribution,
    }
