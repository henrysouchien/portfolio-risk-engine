"""
Core package for risk module data objects and exceptions.

Exports select factor intelligence helpers for convenience.
"""

from .factor_intelligence import (
    load_asset_class_proxies,
    load_industry_buckets,
    fetch_factor_universe,
    build_factor_returns_panel,
)
