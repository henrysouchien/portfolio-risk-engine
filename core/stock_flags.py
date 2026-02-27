"""Stock-level interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_stock_flags(snapshot: dict) -> list[dict]:
    """
    Generate risk characterization flags from stock analysis snapshot.

    Input: dict from StockAnalysisResult.get_agent_snapshot()
    Each flag: {type, severity, message, ...contextual_data}
    """
    flags: list[dict] = []
    vol = snapshot.get("volatility", {}) if isinstance(snapshot, dict) else {}
    reg = snapshot.get("regression", {}) if isinstance(snapshot, dict) else {}
    factors = snapshot.get("factor_exposures", {}) if isinstance(snapshot, dict) else {}
    bond = snapshot.get("bond_analytics", {}) if isinstance(snapshot, dict) else {}

    annual_vol = vol.get("annual_pct")
    beta = reg.get("beta")
    r_squared = reg.get("r_squared")
    sharpe = vol.get("sharpe_ratio")
    max_dd = vol.get("max_drawdown_pct")
    rate_beta_val = bond.get("interest_rate_beta") if isinstance(bond, dict) else None

    if annual_vol is not None and annual_vol > 50:
        flags.append(
            {
                "type": "very_high_volatility",
                "severity": "warning",
                "message": f"Annual volatility is {annual_vol:.0f}% - extremely volatile",
                "annual_vol_pct": annual_vol,
            }
        )
    elif annual_vol is not None and annual_vol > 30:
        flags.append(
            {
                "type": "high_volatility",
                "severity": "info",
                "message": f"Annual volatility is {annual_vol:.0f}% - above average risk",
                "annual_vol_pct": annual_vol,
            }
        )

    if beta is not None and abs(beta) > 2.0:
        flags.append(
            {
                "type": "extreme_beta",
                "severity": "warning",
                "message": f"Beta is {beta:.2f} - moves more than 2x the market",
                "beta": beta,
            }
        )
    elif beta is not None and abs(beta) > 1.5:
        flags.append(
            {
                "type": "high_beta",
                "severity": "info",
                "message": f"Beta is {beta:.2f} - significantly more volatile than market",
                "beta": beta,
            }
        )
    elif beta is not None and abs(beta) < 0.3:
        flags.append(
            {
                "type": "low_beta",
                "severity": "info",
                "message": f"Beta is {beta:.2f} - low market sensitivity (defensive)",
                "beta": beta,
            }
        )

    if r_squared is not None and r_squared < 0.3:
        flags.append(
            {
                "type": "low_r_squared",
                "severity": "info",
                "message": f"R^2 is {r_squared:.2f} - market/factor model explains little of this stock's moves",
                "r_squared": r_squared,
            }
        )

    if max_dd is not None and max_dd < -50.0:
        flags.append(
            {
                "type": "deep_drawdown",
                "severity": "warning",
                "message": f"Max drawdown is {max_dd:.0f}% - experienced severe peak-to-trough decline",
                "max_drawdown_pct": max_dd,
            }
        )

    if sharpe is not None and sharpe < 0:
        flags.append(
            {
                "type": "negative_sharpe",
                "severity": "warning",
                "message": f"Sharpe ratio is {sharpe:.2f} - negative risk-adjusted returns",
                "sharpe_ratio": sharpe,
            }
        )
    elif sharpe is not None and sharpe > 1.5:
        flags.append(
            {
                "type": "strong_sharpe",
                "severity": "success",
                "message": f"Sharpe ratio is {sharpe:.2f} - excellent risk-adjusted returns",
                "sharpe_ratio": sharpe,
            }
        )

    momentum_beta = factors.get("momentum") if isinstance(factors, dict) else None
    value_beta = factors.get("value") if isinstance(factors, dict) else None
    if momentum_beta is not None and abs(momentum_beta) > 0.5:
        direction = "positive" if momentum_beta > 0 else "negative"
        flags.append(
            {
                "type": "momentum_tilt",
                "severity": "info",
                "message": f"Strong {direction} momentum exposure ({momentum_beta:+.2f})",
                "momentum_beta": momentum_beta,
            }
        )
    if value_beta is not None and abs(value_beta) > 0.5:
        style = "value" if value_beta > 0 else "growth"
        flags.append(
            {
                "type": "style_tilt",
                "severity": "info",
                "message": f"Strong {style} tilt (value beta: {value_beta:+.2f})",
                "value_beta": value_beta,
            }
        )

    if rate_beta_val is not None and abs(rate_beta_val) > 1.0:
        flags.append(
            {
                "type": "rate_sensitive",
                "severity": "info",
                "message": f"Interest rate beta is {rate_beta_val:+.2f} - meaningful rate sensitivity",
                "interest_rate_beta": rate_beta_val,
            }
        )

    if (
        annual_vol is not None
        and beta is not None
        and r_squared is not None
        and 15 <= annual_vol <= 25
        and 0.5 <= beta <= 1.2
        and r_squared >= 0.5
    ):
        flags.append(
            {
                "type": "well_behaved",
                "severity": "success",
                "message": "Moderate volatility, reasonable beta, and good model fit - well-behaved stock",
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags
