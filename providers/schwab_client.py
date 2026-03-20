"""Backward-compatible shim for extracted Schwab client helpers."""

from brokerage.schwab.client import (
    check_token_health,
    get_account_hashes,
    get_schwab_client,
    invalidate_schwab_caches,
    is_invalid_grant_error,
    schwab_login,
)

__all__ = [
    "check_token_health",
    "get_account_hashes",
    "get_schwab_client",
    "invalidate_schwab_caches",
    "is_invalid_grant_error",
    "schwab_login",
]
