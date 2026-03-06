"""Shared performance-metrics computation engine.

Called by:
- ``portfolio_risk.calculate_portfolio_performance_metrics``.
- Core/service wrappers that need canonical performance metric payloads.

Contract notes:
- Inputs must be aligned monthly return series with identical DatetimeIndex.
- Output is a JSON-serializable dict consumed by result-object builders.
- CAPM regression may return ``None`` fields with warning metadata when data
  quality thresholds are not met.
"""

from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd
import statsmodels.api as sm

from fmp.compat import fetch_daily_close


def compute_performance_metrics(
    portfolio_returns,
    benchmark_returns,
    risk_free_rate,
    benchmark_ticker,
    start_date,
    end_date,
    min_capm_observations=None,
):
    """Compute portfolio/benchmark return, risk, and CAPM summary metrics.

    Ownership:
    - This is the canonical metrics engine; wrappers should not duplicate
      Sharpe/Sortino/CAPM logic.

    Debug pointer:
    - If alpha/beta fields are missing, inspect CAPM preconditions and warning
      text in the returned payload.
    """

    eps = 1e-12
    if len(portfolio_returns) != len(benchmark_returns):
        raise ValueError("portfolio_returns and benchmark_returns must have the same length")
    if not isinstance(portfolio_returns.index, pd.DatetimeIndex) or not isinstance(
        benchmark_returns.index, pd.DatetimeIndex
    ):
        raise ValueError("portfolio_returns and benchmark_returns must use DatetimeIndex")
    if not portfolio_returns.index.equals(benchmark_returns.index):
        raise ValueError("portfolio_returns and benchmark_returns must have the same index")
    if portfolio_returns.isna().any() or benchmark_returns.isna().any():
        raise ValueError("portfolio_returns and benchmark_returns must not contain NaN values")
    if min_capm_observations is None:
        from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS

        min_capm_observations = DATA_QUALITY_THRESHOLDS.get(
            "min_observations_for_capm_regression", 12
        )

    risk_free_monthly = risk_free_rate / 12

    # Basic performance metrics
    total_months = len(portfolio_returns)
    years = total_months / 12

    # Total returns
    total_portfolio_return = (1 + portfolio_returns).prod() - 1
    total_benchmark_return = (1 + benchmark_returns).prod() - 1

    # Annualized returns (CAGR)
    annualized_portfolio_return = (1 + total_portfolio_return) ** (1 / years) - 1
    annualized_benchmark_return = (1 + total_benchmark_return) ** (1 / years) - 1

    # Volatility (annualized)
    portfolio_volatility = portfolio_returns.std() * np.sqrt(12)
    benchmark_volatility = benchmark_returns.std() * np.sqrt(12)

    # Excess returns
    portfolio_excess = portfolio_returns - risk_free_monthly
    benchmark_excess = benchmark_returns - risk_free_monthly
    tracking_error = (portfolio_returns - benchmark_returns).std() * np.sqrt(12)

    # Risk-adjusted metrics
    sharpe_ratio = (
        (annualized_portfolio_return - risk_free_rate) / portfolio_volatility
        if portfolio_volatility > 0
        else 0
    )
    benchmark_sharpe = (
        (annualized_benchmark_return - risk_free_rate) / benchmark_volatility
        if benchmark_volatility > 0
        else 0
    )

    # Sortino ratio (downside deviation)
    downside_returns = portfolio_returns[portfolio_returns < risk_free_monthly] - risk_free_monthly
    downside_deviation = (
        np.sqrt((downside_returns**2).mean()) * np.sqrt(12) if len(downside_returns) > 0 else 0
    )
    sortino_ratio = (
        (annualized_portfolio_return - risk_free_rate) / downside_deviation
        if downside_deviation > 0
        else 0
    )

    # Information ratio
    excess_return_vs_benchmark = annualized_portfolio_return - annualized_benchmark_return
    information_ratio = excess_return_vs_benchmark / tracking_error if tracking_error > 0 else 0

    # Alpha and Beta (CAPM)
    capm_warning = None
    if len(portfolio_returns) >= min_capm_observations:  # Need sufficient data for regression
        try:
            bench_std = float(benchmark_excess.std(ddof=0))
            port_std = float(portfolio_excess.std(ddof=0))

            # Degenerate series (zero variance) can produce noisy warnings in statsmodels.
            # Use closed-form fallback instead of forcing OLS on singular inputs.
            if bench_std <= eps or port_std <= eps:
                beta = 0.0
                alpha_annual = float(portfolio_excess.mean() * 12.0)
                r_squared = 0.0
            else:
                # Simple linear regression: portfolio_excess = alpha + beta * benchmark_excess
                X = pd.DataFrame(
                    {
                        "const": np.ones(len(benchmark_excess), dtype=float),
                        "benchmark_excess": benchmark_excess.to_numpy(dtype=float),
                    },
                    index=benchmark_excess.index,
                )
                y = portfolio_excess.to_numpy(dtype=float)
                model = sm.OLS(y, X).fit()
                alpha_monthly = float(model.params.iloc[0])  # const
                beta = float(model.params.iloc[1])  # benchmark_excess
                alpha_annual = alpha_monthly * 12.0

                y_hat = model.fittedvalues.to_numpy(dtype=float)
                sst = float(np.sum((y - y.mean()) ** 2))
                sse = float(np.sum((y - y_hat) ** 2))
                r_squared = 1.0 - (sse / sst) if sst > eps else 0.0
        except Exception as exc:
            alpha_annual = None
            beta = None
            r_squared = None
            capm_warning = (
                "CAPM regression failed; alpha/beta/r_squared not computed "
                f"({type(exc).__name__})"
            )
    else:
        alpha_annual = None
        beta = None
        r_squared = None
        capm_warning = (
            "Insufficient data for CAPM regression "
            f"({len(portfolio_returns)} months < {min_capm_observations} required); "
            "alpha/beta/r_squared not computed"
        )

    # Maximum Drawdown
    cumulative_returns = (1 + portfolio_returns).cumprod()
    running_max = cumulative_returns.expanding().max()
    drawdown = (cumulative_returns - running_max) / running_max
    maximum_drawdown = drawdown.min()

    # Calmar Ratio (return / max drawdown)
    calmar_ratio = (
        abs(annualized_portfolio_return / maximum_drawdown) if maximum_drawdown < -0.001 else 0
    )

    # Drawdown metadata
    if maximum_drawdown < -0.001:
        max_dd_trough_idx = drawdown.idxmin()

        pre_trough = drawdown.loc[:max_dd_trough_idx]
        at_peak = pre_trough[pre_trough >= -1e-10]
        if len(at_peak) > 0:
            max_dd_peak_idx = at_peak.index[-1]
        else:
            max_dd_peak_idx = pre_trough.index[0]

        post_trough = drawdown.loc[max_dd_trough_idx:]
        recovered = post_trough[post_trough >= -1e-10]
        recovered_after = recovered[recovered.index > max_dd_trough_idx]
        recovery_date = recovered_after.index[0] if len(recovered_after) > 0 else None

        drawdown_duration_days = (max_dd_trough_idx - max_dd_peak_idx).days
        recovery_days = (recovery_date - max_dd_trough_idx).days if recovery_date else None

        drawdown_metadata = {
            "drawdown_peak_date": max_dd_peak_idx.date().isoformat(),
            "drawdown_trough_date": max_dd_trough_idx.date().isoformat(),
            "drawdown_duration_days": drawdown_duration_days,
            "drawdown_recovery_date": recovery_date.date().isoformat() if recovery_date else None,
            "drawdown_recovery_days": recovery_days,
        }
    else:
        drawdown_metadata = {
            "drawdown_peak_date": None,
            "drawdown_trough_date": None,
            "drawdown_duration_days": None,
            "drawdown_recovery_date": None,
            "drawdown_recovery_days": None,
        }

    # Win rate and average win/loss
    positive_months = portfolio_returns[portfolio_returns > 0]
    negative_months = portfolio_returns[portfolio_returns < 0]
    win_rate = len(positive_months) / len(portfolio_returns) if len(portfolio_returns) > 0 else 0
    avg_win = positive_months.mean() if len(positive_months) > 0 else 0
    avg_loss = negative_months.mean() if len(negative_months) > 0 else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    monthly_returns = {
        k.date().isoformat(): float(v) for k, v in portfolio_returns.round(4).to_dict().items()
    }
    benchmark_monthly_returns = {
        k.date().isoformat(): float(v) for k, v in benchmark_returns.round(4).to_dict().items()
    }

    # Rolling metrics (12-month trailing window, full window only)
    if len(portfolio_returns) >= 12:
        rolling_vol_series = portfolio_returns.rolling(window=12, min_periods=12).std() * np.sqrt(12)
        rolling_mean_excess = (
            portfolio_returns.rolling(window=12, min_periods=12).mean() - risk_free_monthly
        )
        rolling_sharpe_series = (rolling_mean_excess * 12) / rolling_vol_series.replace(0, np.nan)

        rolling_sharpe = {
            k.date().isoformat(): round(float(v), 3)
            for k, v in rolling_sharpe_series.dropna().to_dict().items()
        }
        rolling_volatility = {
            k.date().isoformat(): round(float(v) * 100, 2)
            for k, v in rolling_vol_series.dropna().to_dict().items()
        }
    else:
        rolling_sharpe = {}
        rolling_volatility = {}

    # Performance summary
    performance_metrics = {
        "analysis_period": {
            "start_date": start_date,
            "end_date": end_date,
            "total_months": total_months,
            "years": round(years, 2),
        },
        "returns": {
            "total_return": round(total_portfolio_return * 100, 2),
            "annualized_return": round(annualized_portfolio_return * 100, 2),
            "best_month": round(portfolio_returns.max() * 100, 2),
            "worst_month": round(portfolio_returns.min() * 100, 2),
            "last_month_return": round(float(portfolio_returns.iloc[-1]) * 100, 2),
            "last_month_benchmark_return": round(float(benchmark_returns.iloc[-1]) * 100, 2),
            "positive_months": len(positive_months),
            "negative_months": len(negative_months),
            "win_rate": round(win_rate * 100, 1),
        },
        "risk_metrics": {
            "volatility": round(portfolio_volatility * 100, 2),
            "maximum_drawdown": round(maximum_drawdown * 100, 2),
            "downside_deviation": round(downside_deviation * 100, 2),
            "tracking_error": round(tracking_error * 100, 2),
            **drawdown_metadata,
        },
        "risk_adjusted_returns": {
            "sharpe_ratio": round(sharpe_ratio, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "information_ratio": round(information_ratio, 3),
            "calmar_ratio": round(calmar_ratio, 3),
        },
        "benchmark_analysis": {
            "benchmark_ticker": benchmark_ticker,
            "alpha_annual": round(alpha_annual * 100, 2) if alpha_annual is not None else None,
            "beta": round(beta, 3) if beta is not None else None,
            "r_squared": round(r_squared, 3) if r_squared is not None else None,
            "excess_return": round(excess_return_vs_benchmark * 100, 2),
        },
        "benchmark_comparison": {
            "portfolio_total_return": round(total_portfolio_return * 100, 2),
            "benchmark_total_return": round(total_benchmark_return * 100, 2),
            "portfolio_return": round(annualized_portfolio_return * 100, 2),
            "benchmark_return": round(annualized_benchmark_return * 100, 2),
            "portfolio_volatility": round(portfolio_volatility * 100, 2),
            "benchmark_volatility": round(benchmark_volatility * 100, 2),
            "portfolio_sharpe": round(sharpe_ratio, 3),
            "benchmark_sharpe": round(benchmark_sharpe, 3),
        },
        "monthly_stats": {
            "average_monthly_return": round(portfolio_returns.mean() * 100, 2),
            "average_win": round(avg_win * 100, 2),
            "average_loss": round(avg_loss * 100, 2),
            "win_loss_ratio": round(win_loss_ratio, 2),
        },
        "risk_free_rate": round(risk_free_rate * 100, 2),
        "monthly_returns": monthly_returns,
        "benchmark_monthly_returns": benchmark_monthly_returns,
        "rolling_sharpe": rolling_sharpe,
        "rolling_volatility": rolling_volatility,
    }
    if capm_warning:
        performance_metrics["warnings"] = [capm_warning]

    return performance_metrics


def compute_recent_returns(
    weights: Dict[str, float],
    benchmark_ticker: str = "SPY",
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[float]]:
    """Compute best-effort 1D/1W returns for portfolio and benchmark in percent."""
    all_none: Dict[str, Optional[float]] = {
        "last_day_return": None,
        "last_week_return": None,
        "last_day_benchmark_return": None,
        "last_week_benchmark_return": None,
    }

    try:
        if not weights:
            return all_none

        start_date = date.today() - timedelta(days=14)
        ticker_daily_returns: Dict[str, pd.Series] = {}
        ticker_weights: Dict[str, float] = {}

        for ticker, weight in weights.items():
            try:
                w = float(weight)
                if not np.isfinite(w) or abs(w) <= 1e-12:
                    continue

                close_prices = fetch_daily_close(
                    ticker,
                    start_date=start_date,
                    fmp_ticker_map=fmp_ticker_map,
                ).sort_index()
                daily_returns = close_prices.pct_change().dropna()
                if daily_returns.empty:
                    continue

                ticker_daily_returns[ticker] = daily_returns
                ticker_weights[ticker] = w
            except Exception:
                continue

        last_day_return = None
        last_week_return = None
        if ticker_daily_returns:
            returns_df = pd.DataFrame(ticker_daily_returns).sort_index()
            weights_series = pd.Series(ticker_weights)

            weighted_sum = returns_df.mul(weights_series, axis=1).sum(axis=1)
            available_weight_sum = returns_df.notna().mul(weights_series, axis=1).sum(axis=1)
            available_weight_sum = available_weight_sum.where(available_weight_sum.abs() > 1e-12)

            portfolio_daily = (weighted_sum / available_weight_sum).dropna()
            if not portfolio_daily.empty:
                last_day_return = float(portfolio_daily.iloc[-1]) * 100.0
                if len(portfolio_daily) >= 5:
                    last_week_return = float((1.0 + portfolio_daily.tail(5)).prod() - 1.0) * 100.0

        last_day_benchmark_return = None
        last_week_benchmark_return = None
        try:
            benchmark_close = fetch_daily_close(
                benchmark_ticker,
                start_date=start_date,
                fmp_ticker_map=fmp_ticker_map,
            ).sort_index()
            benchmark_daily = benchmark_close.pct_change().dropna()
            if not benchmark_daily.empty:
                last_day_benchmark_return = float(benchmark_daily.iloc[-1]) * 100.0
                if len(benchmark_daily) >= 5:
                    last_week_benchmark_return = (
                        float((1.0 + benchmark_daily.tail(5)).prod() - 1.0) * 100.0
                    )
        except Exception:
            pass

        return {
            "last_day_return": round(last_day_return, 2) if last_day_return is not None else None,
            "last_week_return": round(last_week_return, 2) if last_week_return is not None else None,
            "last_day_benchmark_return": (
                round(last_day_benchmark_return, 2)
                if last_day_benchmark_return is not None
                else None
            ),
            "last_week_benchmark_return": (
                round(last_week_benchmark_return, 2)
                if last_week_benchmark_return is not None
                else None
            ),
        }
    except Exception:
        return all_none
