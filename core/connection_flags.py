"""Interpretive flags for the unified connection-status MCP tool."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert a value to a finite float when possible."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _sort_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort flags by severity: error > warning > info > success."""
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))


def generate_connection_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged connection flags from a provider snapshot."""
    if not isinstance(snapshot, dict):
        return []

    providers = snapshot.get("providers", {})
    providers = providers if isinstance(providers, dict) else {}
    summary = snapshot.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    health_probed = bool(summary.get("health_probed", False))

    flags: list[dict[str, Any]] = []

    for provider_name in ("snaptrade", "plaid", "schwab", "ibkr"):
        provider = providers.get(provider_name, {})
        if not isinstance(provider, dict):
            continue
        error = provider.get("error")
        if error:
            flags.append(
                {
                    "flag": "provider_error",
                    "severity": "error",
                    "message": f"{provider_name} provider error: {error}",
                    "provider": provider_name,
                }
            )

    schwab = providers.get("schwab", {})
    if isinstance(schwab, dict):
        schwab_connection = schwab.get("connection", {})
        schwab_connection = schwab_connection if isinstance(schwab_connection, dict) else {}
        schwab_status = str(schwab_connection.get("status") or "")

        if bool(schwab.get("enabled")) and schwab_status == "token_missing":
            flags.append(
                {
                    "flag": "schwab_token_missing",
                    "severity": "error",
                    "message": "Schwab is enabled but no token file is present.",
                }
            )

        if health_probed and bool(schwab_connection.get("near_refresh_expiry")):
            flags.append(
                {
                    "flag": "schwab_token_expired",
                    "severity": "error",
                    "message": "Schwab refresh token appears expired and requires re-authentication.",
                }
            )

        days_remaining = _to_float(schwab_connection.get("refresh_token_days_remaining"))
        if (
            health_probed
            and not bool(schwab_connection.get("near_refresh_expiry"))
            and days_remaining is not None
            and days_remaining <= 2
        ):
            flags.append(
                {
                    "flag": "schwab_token_expiring",
                    "severity": "warning",
                    "message": f"Schwab refresh token expires in {days_remaining:.2f} days.",
                    "refresh_token_days_remaining": days_remaining,
                }
            )

        if health_probed and schwab_status == "degraded":
            warnings = schwab_connection.get("warnings")
            if isinstance(warnings, list) and warnings:
                warning_text = str(warnings[0])
            else:
                warning_text = "Schwab connection has health warnings."
            flags.append(
                {
                    "flag": "schwab_degraded",
                    "severity": "warning",
                    "message": warning_text,
                }
            )

    plaid = providers.get("plaid", {})
    if isinstance(plaid, dict):
        for item in plaid.get("connections", []) if isinstance(plaid.get("connections"), list) else []:
            if not isinstance(item, dict) or not bool(item.get("needs_reauth")):
                continue
            institution = str(item.get("institution") or item.get("item_id") or "unknown")
            flags.append(
                {
                    "flag": "plaid_needs_reauth",
                    "severity": "error",
                    "message": f"Plaid connection requires re-authentication: {institution}.",
                    "institution": institution,
                    "item_id": item.get("item_id"),
                }
            )

    if health_probed:
        snaptrade = providers.get("snaptrade", {})
        if isinstance(snaptrade, dict):
            for connection in (
                snaptrade.get("connections", [])
                if isinstance(snaptrade.get("connections"), list)
                else []
            ):
                if not isinstance(connection, dict):
                    continue
                institution = str(
                    connection.get("institution")
                    or connection.get("authorization_id")
                    or "unknown"
                )
                if bool(connection.get("disabled")):
                    flags.append(
                        {
                            "flag": "snaptrade_disabled",
                            "severity": "error",
                            "message": f"SnapTrade connection is disabled: {institution}.",
                            "authorization_id": connection.get("authorization_id"),
                        }
                    )
                elif connection.get("data_ok") is False:
                    flags.append(
                        {
                            "flag": "snaptrade_data_probe_failed",
                            "severity": "warning",
                            "message": f"SnapTrade data probe failed: {institution}.",
                            "authorization_id": connection.get("authorization_id"),
                        }
                    )

        ibkr = providers.get("ibkr", {})
        if isinstance(ibkr, dict):
            ibkr_connection = ibkr.get("connection", {})
            ibkr_connection = ibkr_connection if isinstance(ibkr_connection, dict) else {}
            if ibkr_connection.get("gateway_reachable") is False:
                flags.append(
                    {
                        "flag": "ibkr_gateway_unreachable",
                        "severity": "error",
                        "message": "IBKR Gateway is unreachable.",
                    }
                )

    total_connections = int(summary.get("total_connections") or 0)
    has_provider_errors = any(flag.get("flag") == "provider_error" for flag in flags)
    if total_connections == 0 and not has_provider_errors:
        flags.append(
            {
                "flag": "no_connections",
                "severity": "warning",
                "message": "No brokerage connections were found.",
            }
        )

    has_attention_flags = any(flag.get("severity") in {"error", "warning"} for flag in flags)
    if health_probed and not has_attention_flags:
        flags.append(
            {
                "flag": "all_healthy",
                "severity": "success",
                "message": "All discovered connections are healthy.",
            }
        )

    return _sort_flags(flags)
