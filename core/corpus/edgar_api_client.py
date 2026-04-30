"""HTTP client for edgar_api at edgarparser.com.

Replaces direct Python imports of edgar_parser. Phase 3+4 parser is
deployed at edgarparser.com; the public PyPI edgar_parser package is
frozen at v0.3.0 (pre-Phase-3+4) and must not be used.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


_DEFAULT_TIMEOUT = 600.0
_TIMEOUT_ENV_VAR = "EDGAR_API_TIMEOUT"


def _resolve_default_timeout() -> float:
    """Read EDGAR_API_TIMEOUT env var (seconds); fall back to 600s.

    Edgar_updater's nginx ceiling is 600s. Cold-cache mega-cap filings can take
    30-200s, so the default must match that server-side ceiling.
    """
    raw = os.getenv(_TIMEOUT_ENV_VAR, "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        timeout = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT
    if timeout <= 0:
        return _DEFAULT_TIMEOUT
    return timeout


class EdgarAPIError(Exception):
    """API call to edgar_api failed (network, auth, rate limit, server error)."""


def _resolve_timeout(timeout: float | None) -> float:
    if timeout is None:
        return _resolve_default_timeout()
    return timeout


def _config() -> tuple[str, str]:
    base_url = os.getenv("EDGAR_API_URL", "").rstrip("/")
    api_key = os.getenv("EDGAR_API_KEY", "")
    if not base_url or not api_key:
        raise EdgarAPIError("EDGAR_API_URL and EDGAR_API_KEY must be set in environment")
    return base_url, api_key


def _request_json(path: str, params: dict[str, Any], *, timeout: float | None) -> dict[str, Any]:
    base_url, api_key = _config()
    resolved_timeout = _resolve_timeout(timeout)
    try:
        resp = httpx.get(
            f"{base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=resolved_timeout,
        )
    except httpx.RequestError as exc:
        raise EdgarAPIError(f"network error calling {path}: {exc}") from exc
    if resp.status_code != 200:
        raise EdgarAPIError(f"HTTP {resp.status_code} from {path}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise EdgarAPIError(f"invalid JSON from {path}: {exc}") from exc


def get_filing_sections(
    ticker: str,
    year: int,
    quarter: int,
    *,
    sections: list[str] | None = None,
    format: str = "full",
    source: str | None = None,
    max_words: int | str | None = None,
    include_tables: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "ticker": ticker,
        "year": year,
        "quarter": quarter,
        "format": format,
    }
    if sections:
        params["sections"] = ",".join(sections)
    if source:
        params["source"] = source
    if max_words is not None:
        params["max_words"] = str(max_words)
    if include_tables:
        params["include_tables"] = "true"
    return _request_json("/api/sections", params, timeout=timeout)


def get_filings(
    ticker: str,
    year: int,
    quarter: int,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    return _request_json(
        "/api/filings",
        {"ticker": ticker, "year": year, "quarter": quarter},
        timeout=timeout,
    )


__all__ = ["EdgarAPIError", "get_filing_sections", "get_filings"]
