"""Logging shim.

Uses monorepo logging when available. Falls back to stdlib logging and no-op
instrumentation decorators in standalone mode.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable


try:  # pragma: no cover - preferred in monorepo
    from utils.logging import (  # type: ignore
        portfolio_logger,
        log_operation,
        log_timing,
        log_errors,
        log_portfolio_operation,
        log_critical_alert,
        log_service_health,
    )
except Exception:  # pragma: no cover - standalone fallback
    portfolio_logger = logging.getLogger("portfolio_risk_engine")

    def _identity_decorator(_arg: Any = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            return wrapper

        return deco

    def log_operation(_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return _identity_decorator()

    def log_timing(_threshold: float = 0.0) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return _identity_decorator()

    def log_errors(_severity: str = "medium") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return _identity_decorator()

    def log_portfolio_operation(_event: str, _details: dict[str, Any] | None = None, execution_time: float | None = None) -> dict[str, Any]:
        if _details:
            portfolio_logger.info("[%s] %s", _event, _details)
        else:
            portfolio_logger.info("[%s]", _event)
        return {"event": _event, "details": _details or {}, "execution_time": execution_time}

    def log_critical_alert(_alert_type: str, _severity: str, message: str, _action: str | None = None, details: dict[str, Any] | None = None) -> None:
        portfolio_logger.warning("critical_alert: %s %s", message, details or {})

    def log_service_health(service: str, status: str, response_time: float | None = None, details: dict[str, Any] | None = None) -> None:
        portfolio_logger.info("service_health: %s %s %.3f %s", service, status, response_time or 0.0, details or {})
