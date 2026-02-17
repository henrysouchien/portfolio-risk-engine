# Plan: Centralized Cache Control

**Status:** COMPLETE (v3 — 3 rounds of Codex review, implemented + tested)

## Context

Cache infrastructure is scattered across the codebase: `ServiceManager` aggregates 5 service caches with TTLCache, FMP has 5 `@lru_cache` functions, IBKR has a disk cache with 5,500+ parquet files, and the admin endpoints in `routes/admin.py` hardcode only 3 of these. There's no unified way to inspect or clear all caches.

This plan formalizes a `CacheControl` Protocol + `CacheManager` registry, adds a CLI tool (`run_cache.py`), and wires `ServiceManager` to use it.

**Scope:** Backend + CLI only. No MCP tools, no admin UI (future work).

**Deferred:** `routes/admin.py` changes are OUT OF SCOPE — the admin endpoints have fixed Pydantic response schemas (`CacheStatusResponse`, `ClearCacheResponse`) and operate on live app instances. Wiring them to CacheManager requires injecting live service instances at app startup, which is a separate effort. The CLI uses `build_cache_manager()` which creates fresh instances (fine for CLI, not for admin endpoints that need the live app state).

---

## Existing Infrastructure

### ServiceCacheMixin (`services/cache_mixin.py`)
```python
class ServiceCacheMixin:
    def _init_service_cache(self):
        self._cache = TTLCache(maxsize=SERVICE_CACHE_MAXSIZE, ttl=SERVICE_CACHE_TTL)
        self._raw_cache = TTLCache(maxsize=SERVICE_CACHE_MAXSIZE, ttl=SERVICE_CACHE_TTL)
        self._lock = threading.Lock()
```

### Service method availability

| Service | `clear_cache` | `get_cache_stats` | `health_check` |
|---------|:---:|:---:|:---:|
| PortfolioService | Y | Y | Y |
| OptimizationService | Y | Y | Y |
| StockService | Y | Y | Y |
| ScenarioService | Y | Y | Y |
| FactorIntelligenceService | Y | Y | **N** |
| ReturnsService | Y | Y | Y |
| PortfolioContextService | Y | **N** | **N** |
| SecurityTypeService (static) | Y | Y | Y |

### ServiceManager (`services/service_manager.py`)
- Has `clear_all_caches()`, `get_cache_stats()`, `health_check()` — hardcoded to 5 services
- `health_check()` returns top-level `cache_enabled` key — must preserve this

### FMP LRU Caches (`fmp/` package)
5 data `@lru_cache` functions (excluding config loaders like `get_client()`):
- `fmp/compat.py:26` — `_minor_currency_divisor_for_symbol(fmp_symbol)` maxsize=DATA_LOADER_LRU_SIZE
- `fmp/compat.py:87` — `_fetch_monthly_close_cached(ticker, fmp_symbol, start_date, end_date)` maxsize=DATA_LOADER_LRU_SIZE
- `fmp/compat.py:182` — `_fetch_monthly_total_return_cached(ticker, fmp_symbol, start_date, end_date)` maxsize=DATA_LOADER_LRU_SIZE
- `fmp/compat.py:322` — `fetch_monthly_treasury_rates(maturity, start_date, end_date)` maxsize=TREASURY_RATE_LRU_SIZE
- `fmp/fx.py:95` — `_get_spot_fx_cached(currency, cache_date)` maxsize=32

**Not included (excluded from this phase):**
- IBKR `@lru_cache` in `ibkr/contracts.py`, `ibkr/flex.py`, `ibkr/compat.py` — maxsize=1 YAML config loaders, clearing is no-op in practice
- `core/factor_intelligence.py` — has several `@lru_cache` data loaders (maxsize=DATA_LOADER_LRU_SIZE), but these are tightly coupled to the factor engine internals. Can be added in a future phase.

### IBKR Disk Cache (`ibkr/cache.py`)
- Parquet+zstd files in `cache/ibkr/` directory
- File pattern: `ibkr_{md5_hash}.parquet`
- 4-hour TTL for current-month requests, infinite for historical
- Has `get_cached()` and `put_cache()` — no stats or clear functions

### SecurityTypeService (`services/security_type_service.py`)
- `clear_cache()` (line 655) — clears DB cache rows
- `clear_cash_mappings_cache()` (line 1377) — separate in-memory cash mapping cache
- Both must be called for full clear

---

## Implementation

### File 1: `services/cache_control.py` (NEW)

```python
"""CacheControl protocol and CacheManager registry."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class CacheControl(Protocol):
    """Protocol for any component exposing cache controls."""

    cache_name: str

    def clear_cache(self) -> None: ...
    def get_cache_stats(self) -> Dict[str, Any]: ...
    def health_check(self) -> Dict[str, Any]: ...


class CacheManager:
    """Registry that aggregates all CacheControl implementations."""

    def __init__(self) -> None:
        self._caches: Dict[str, CacheControl] = {}

    def register(self, cache: CacheControl) -> None:
        self._caches[cache.cache_name] = cache

    def clear_all(self) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        for name, cache in self._caches.items():
            try:
                cache.clear_cache()
                results[name] = {"success": True}
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}
        return results

    def get_all_stats_safe(self) -> Dict[str, Dict[str, Any]]:
        """Like get_all_stats but isolates per-cache failures."""
        results: Dict[str, Dict[str, Any]] = {}
        for name, c in self._caches.items():
            try:
                results[name] = c.get_cache_stats()
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    def get_all_health_safe(self) -> Dict[str, Dict[str, Any]]:
        """Like get_all_health but isolates per-cache failures."""
        results: Dict[str, Dict[str, Any]] = {}
        for name, c in self._caches.items():
            try:
                results[name] = c.health_check()
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
        return results

    def clear(self, name: str) -> None:
        cache = self._caches.get(name)
        if cache is None:
            raise KeyError(f"Unknown cache: {name}. Available: {self.list_caches()}")
        cache.clear_cache()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {name: c.get_cache_stats() for name, c in self._caches.items()}

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        return {name: c.health_check() for name, c in self._caches.items()}

    def get_cache(self, name: str) -> Optional[CacheControl]:
        return self._caches.get(name)

    def list_caches(self) -> List[str]:
        return sorted(self._caches.keys())


def build_cache_manager() -> CacheManager:
    """Factory: assemble CacheManager with all known caches.

    Creates fresh service instances — suitable for CLI usage.
    For live app usage, inject instances via ServiceManager._get_cache_manager().
    """
    from services.cache_adapters import (
        ContextCacheAdapter,
        FMPCacheAdapter,
        IBKRDiskCacheAdapter,
        SecurityTypeCacheAdapter,
        ServiceCacheAdapter,
    )

    manager = CacheManager()

    # --- ServiceManager's 5 TTLCache services ---
    from services.portfolio_service import PortfolioService
    from services.optimization_service import OptimizationService
    from services.stock_service import StockService
    from services.scenario_service import ScenarioService
    from services.factor_intelligence_service import FactorIntelligenceService

    for name, cls in [
        ("portfolio_service", PortfolioService),
        ("optimization_service", OptimizationService),
        ("stock_service", StockService),
        ("scenario_service", ScenarioService),
        ("factor_intelligence_service", FactorIntelligenceService),
    ]:
        manager.register(ServiceCacheAdapter(cls(cache_results=True), name))

    # --- Additional services (need dedicated adapters) ---
    from services.returns_service import ReturnsService

    manager.register(ServiceCacheAdapter(ReturnsService(), "returns_service"))
    manager.register(ContextCacheAdapter())
    manager.register(SecurityTypeCacheAdapter())

    # --- FMP lru_caches ---
    manager.register(FMPCacheAdapter())

    # --- IBKR disk cache ---
    manager.register(IBKRDiskCacheAdapter())

    return manager
```

### File 2: `services/cache_adapters.py` (NEW)

```python
"""Adapter classes that wrap existing caches to satisfy CacheControl protocol."""

from __future__ import annotations

from typing import Any, Dict


class ServiceCacheAdapter:
    """Wraps any service with clear_cache/get_cache_stats/health_check.

    For services missing health_check (e.g. FactorIntelligenceService),
    synthesizes a response from get_cache_stats().
    """

    def __init__(self, service: Any, cache_name: str) -> None:
        self._service = service
        self.cache_name = cache_name

    def clear_cache(self) -> None:
        self._service.clear_cache()

    def get_cache_stats(self) -> Dict[str, Any]:
        return self._service.get_cache_stats()

    def health_check(self) -> Dict[str, Any]:
        if hasattr(self._service, "health_check"):
            return self._service.health_check()
        # Synthesize from stats for services missing health_check
        stats = self.get_cache_stats()
        return {"status": "healthy", **stats}


class ContextCacheAdapter:
    """Dedicated adapter for PortfolioContextService.

    Only has clear_cache(); stats and health are synthesized from
    the TTLCache internals.
    """

    cache_name = "context_service"

    def _get_service(self):
        from services.portfolio.context_service import PortfolioContextService
        if not hasattr(self, "_service"):
            self._service = PortfolioContextService()
        return self._service

    def clear_cache(self) -> None:
        svc = self._get_service()
        svc.clear_cache()

    def get_cache_stats(self) -> Dict[str, Any]:
        svc = self._get_service()
        return {
            "cache_enabled": True,
            "cache_size": len(svc.context_cache),
        }

    def health_check(self) -> Dict[str, Any]:
        stats = self.get_cache_stats()
        return {"status": "healthy", **stats}


class SecurityTypeCacheAdapter:
    """Dedicated adapter for SecurityTypeService (static methods).

    Calls both clear_cache() and clear_cash_mappings_cache() for full clear.
    Note: SecurityTypeService.clear_cache() returns a status dict (doesn't raise).
    We check it and raise on failure so CacheManager.clear_all() can report it.
    """

    cache_name = "security_type_service"

    def clear_cache(self) -> None:
        from services.security_type_service import SecurityTypeService
        result = SecurityTypeService.clear_cache()
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("message", "SecurityType cache clear failed"))
        SecurityTypeService.clear_cash_mappings_cache()

    def get_cache_stats(self) -> Dict[str, Any]:
        from services.security_type_service import SecurityTypeService
        return SecurityTypeService.get_cache_stats()

    def health_check(self) -> Dict[str, Any]:
        from services.security_type_service import SecurityTypeService
        return SecurityTypeService.health_check()


class FMPCacheAdapter:
    """Wraps the 5 data @lru_cache functions in fmp/ package."""

    cache_name = "fmp_lru"

    def _get_functions(self) -> list:
        from fmp.compat import (
            _minor_currency_divisor_for_symbol,
            _fetch_monthly_close_cached,
            _fetch_monthly_total_return_cached,
            fetch_monthly_treasury_rates,
        )
        from fmp.fx import _get_spot_fx_cached

        return [
            _minor_currency_divisor_for_symbol,
            _fetch_monthly_close_cached,
            _fetch_monthly_total_return_cached,
            fetch_monthly_treasury_rates,
            _get_spot_fx_cached,
        ]

    def clear_cache(self) -> None:
        for func in self._get_functions():
            func.cache_clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        total_size = 0
        total_hits = 0
        total_misses = 0
        details: Dict[str, Dict[str, Any]] = {}

        for func in self._get_functions():
            info = func.cache_info()
            total_size += info.currsize
            total_hits += info.hits
            total_misses += info.misses
            details[func.__name__] = {
                "size": info.currsize,
                "maxsize": info.maxsize,
                "hits": info.hits,
                "misses": info.misses,
            }

        total = total_hits + total_misses
        return {
            "cache_enabled": True,
            "cache_size": total_size,
            "hit_rate": round(total_hits / total, 4) if total > 0 else 0.0,
            "details": details,
        }

    def health_check(self) -> Dict[str, Any]:
        stats = self.get_cache_stats()
        return {
            "status": "healthy",
            "cache_enabled": True,
            "total_entries": stats["cache_size"],
        }


class IBKRDiskCacheAdapter:
    """Wraps IBKR parquet disk cache.

    clear_cache() satisfies the Protocol (no args, returns None).
    clear_by_age() is IBKR-specific for the CLI --age flag.
    """

    cache_name = "ibkr_disk"

    def clear_cache(self) -> None:
        from ibkr.cache import clear_disk_cache
        clear_disk_cache()

    def clear_by_age(self, older_than_hours: int) -> Dict[str, Any]:
        """IBKR-specific: clear only files older than N hours."""
        from ibkr.cache import clear_disk_cache
        return clear_disk_cache(older_than_hours=older_than_hours)

    def get_cache_stats(self) -> Dict[str, Any]:
        from ibkr.cache import disk_cache_stats
        return disk_cache_stats()

    def health_check(self) -> Dict[str, Any]:
        stats = self.get_cache_stats()
        return {
            "status": "healthy",
            "cache_enabled": True,
            "file_count": stats["file_count"],
            "size_mb": stats["total_mb"],
        }
```

### File 3: `ibkr/cache.py` — Add two functions (EDIT)

Add `Dict` to existing `from typing import Any` import → `from typing import Any, Dict`.

Append after the existing `put_cache()` function (after line 202):

```python
def disk_cache_stats(base_dir: str | Path | None = None) -> Dict[str, Any]:
    """Return stats for the IBKR parquet disk cache."""
    cache_path = _cache_dir(base_dir)
    files = list(cache_path.glob("ibkr_*.parquet"))

    if not files:
        return {"file_count": 0, "total_bytes": 0, "total_mb": 0.0,
                "oldest": None, "newest": None, "cache_enabled": True}

    total_bytes = 0
    mtimes: list[float] = []
    for f in files:
        try:
            st = f.stat()
            total_bytes += st.st_size
            mtimes.append(st.st_mtime)
        except OSError:
            continue

    if not mtimes:
        return {"file_count": 0, "total_bytes": 0, "total_mb": 0.0,
                "oldest": None, "newest": None, "cache_enabled": True}

    return {
        "file_count": len(mtimes),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "oldest": datetime.fromtimestamp(min(mtimes), tz=UTC).isoformat(),
        "newest": datetime.fromtimestamp(max(mtimes), tz=UTC).isoformat(),
        "cache_enabled": True,
    }


def clear_disk_cache(
    base_dir: str | Path | None = None,
    older_than_hours: int | None = None,
) -> Dict[str, Any]:
    """Remove IBKR parquet cache files, optionally filtered by age.

    Args:
        base_dir: Override project root for cache directory.
        older_than_hours: If set, only remove files older than this many hours.
            Must be >= 0.

    Returns:
        Summary dict with files_removed, bytes_freed, mb_freed, errors.
    """
    if older_than_hours is not None and older_than_hours < 0:
        raise ValueError(f"older_than_hours must be >= 0, got {older_than_hours}")

    cache_path = _cache_dir(base_dir)
    files = list(cache_path.glob("ibkr_*.parquet"))
    removed = 0
    freed = 0
    errors: list[str] = []

    for f in files:
        try:
            st = f.stat()
            if older_than_hours is not None:
                age_h = (time.time() - st.st_mtime) / 3600.0
                if age_h <= older_than_hours:
                    continue
            freed += st.st_size
            f.unlink(missing_ok=True)
            removed += 1
        except OSError as e:
            errors.append(f"{f.name}: {e}")

    result: Dict[str, Any] = {
        "files_removed": removed,
        "bytes_freed": freed,
        "mb_freed": round(freed / (1024 * 1024), 2),
    }
    if errors:
        result["errors"] = errors
    return result
```

### File 4: `run_cache.py` — CLI tool (NEW)

```python
#!/usr/bin/env python3
"""Cache management CLI.

Usage:
    python run_cache.py list                       # List all registered caches
    python run_cache.py stats [CACHE]              # Show stats (all or specific)
    python run_cache.py health                     # Health check all caches
    python run_cache.py clear [CACHE]              # Clear all or specific cache
    python run_cache.py clear ibkr_disk --age 24   # Clear IBKR files >24h old

    Add --json to stats/health for machine-readable output.
"""

import argparse
import json
import sys

from services.cache_control import build_cache_manager, CacheManager


def _print_table(stats: dict) -> None:
    """Pretty-print cache stats."""
    for name in sorted(stats):
        data = stats[name]
        print(f"\n  {name}:")
        for k, v in data.items():
            if isinstance(v, dict):
                print(f"    {k}:")
                for k2, v2 in v.items():
                    print(f"      {k2}: {v2}")
            else:
                print(f"    {k}: {v}")


def cmd_list(mgr: CacheManager, _args: argparse.Namespace) -> None:
    caches = mgr.list_caches()
    print(f"\nRegistered caches ({len(caches)}):\n")
    for name in caches:
        print(f"  - {name}")
    print()


def cmd_stats(mgr: CacheManager, args: argparse.Namespace) -> None:
    if args.cache_name:
        cache = mgr.get_cache(args.cache_name)
        if not cache:
            print(f"Error: '{args.cache_name}' not found. "
                  f"Use 'list' to see available caches.", file=sys.stderr)
            sys.exit(1)
        try:
            data = {args.cache_name: cache.get_cache_stats()}
        except Exception as e:
            print(f"Error getting stats for {args.cache_name}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        data = mgr.get_all_stats_safe()

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print("\n=== Cache Statistics ===")
        _print_table(data)
        print()


def cmd_health(mgr: CacheManager, args: argparse.Namespace) -> None:
    data = mgr.get_all_health_safe()
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print("\n=== Cache Health ===\n")
        for name in sorted(data):
            status = data[name].get("status", "unknown")
            icon = "OK" if status in ("healthy", "ok") else "!!"
            print(f"  [{icon}] {name}: {status}")
        print()


def cmd_clear(mgr: CacheManager, args: argparse.Namespace) -> None:
    if args.cache_name:
        cache = mgr.get_cache(args.cache_name)
        if not cache:
            print(f"Error: '{args.cache_name}' not found.", file=sys.stderr)
            sys.exit(1)
        try:
            # Special --age handling for ibkr_disk (adapter-specific method)
            if args.cache_name == "ibkr_disk" and args.age is not None:
                from services.cache_adapters import IBKRDiskCacheAdapter
                if not isinstance(cache, IBKRDiskCacheAdapter):
                    print("Error: --age is only supported for ibkr_disk", file=sys.stderr)
                    sys.exit(1)
                result = cache.clear_by_age(older_than_hours=args.age)
                print(f"Cleared ibkr_disk: {result}")
            else:
                cache.clear_cache()
                print(f"Cleared: {args.cache_name}")
        except Exception as e:
            print(f"Error clearing {args.cache_name}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        results = mgr.clear_all()
        ok = sum(1 for r in results.values() if r.get("success"))
        print(f"\nCleared {ok}/{len(results)} caches")
        for name, r in sorted(results.items()):
            status = "OK" if r.get("success") else f"FAIL: {r.get('error')}"
            print(f"  {name}: {status}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List registered caches")

    p_stats = sub.add_parser("stats", help="Show cache statistics")
    p_stats.add_argument("cache_name", nargs="?", help="Specific cache (optional)")
    p_stats.add_argument("--json", action="store_true", help="JSON output")

    p_health = sub.add_parser("health", help="Health check all caches")
    p_health.add_argument("--json", action="store_true", help="JSON output")

    p_clear = sub.add_parser("clear", help="Clear cache(s)")
    p_clear.add_argument("cache_name", nargs="?",
                         help="Specific cache (optional, clears all if omitted)")
    p_clear.add_argument("--age", type=int,
                         help="For ibkr_disk: only clear files older than N hours")

    args = parser.parse_args()
    mgr = build_cache_manager()

    {"list": cmd_list, "stats": cmd_stats,
     "health": cmd_health, "clear": cmd_clear}[args.command](mgr, args)


if __name__ == "__main__":
    main()
```

### File 5: `services/service_manager.py` (EDIT)

Replace lines 105-138 (the three hardcoded methods) with CacheManager delegation.
**Must preserve:** existing decorator chain, method signatures, and the top-level `cache_enabled` key in `health_check()` return value.

```python
    @log_error_handling("medium")
    @log_portfolio_operation_decorator("service_manager_clear_all_caches")
    @log_cache_operations("service_manager")
    @log_performance(0.5)
    def clear_all_caches(self):
        """Clear all service caches."""
        import logging
        logger = logging.getLogger(__name__)
        results = self._get_cache_manager().clear_all()
        failed = {n: r for n, r in results.items() if not r.get("success")}
        for name, result in failed.items():
            logger.warning("Failed to clear cache %s: %s", name, result.get("error"))
        if failed:
            raise RuntimeError(f"Cache clear failed for: {', '.join(failed)}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for all services."""
        return self._get_cache_manager().get_all_stats()

    @log_error_handling("medium")
    @log_portfolio_operation_decorator("service_manager_health_check")
    @log_performance(0.5)
    def health_check(self) -> Dict[str, Any]:
        """Check health of all services."""
        result = self._get_cache_manager().get_all_health()
        result['cache_enabled'] = self.cache_results  # preserve existing contract
        return result

    def _get_cache_manager(self):
        """Lazy-init a CacheManager wrapping this manager's own service instances."""
        if not hasattr(self, '_cache_manager'):
            from services.cache_adapters import ServiceCacheAdapter
            from services.cache_control import CacheManager
            cm = CacheManager()
            for name, svc in [
                ("portfolio_service", self.portfolio_service),
                ("optimization_service", self.optimization_service),
                ("stock_service", self.stock_service),
                ("scenario_service", self.scenario_service),
                ("factor_intelligence_service", self.factor_intelligence_service),
            ]:
                cm.register(ServiceCacheAdapter(svc, name))
            self._cache_manager = cm
        return self._cache_manager
```

**Note:** ServiceManager only wraps its own 5 services (same as before). The full 10-cache manager is in `build_cache_manager()` for CLI use.

### File 6: `tests/services/test_cache_control.py` (NEW)

Test coverage:

**Protocol & CacheManager:**
1. All 5 adapter classes satisfy `isinstance(adapter, CacheControl)`
2. `CacheManager.register` + `list_caches` returns sorted names
3. `CacheManager.clear_all` calls `clear_cache` on each, returns success/failure dict
4. `CacheManager.clear(name)` clears specific, raises `KeyError` on unknown
5. `CacheManager.get_all_stats` aggregates from all registered caches

**ServiceCacheAdapter:**
6. Delegates `clear_cache`/`get_cache_stats`/`health_check` to mock service
7. Synthesizes `health_check` when service lacks it (e.g. FactorIntelligenceService)

**ContextCacheAdapter:**
8. `clear_cache` delegates to `PortfolioContextService.clear_cache()`
9. `get_cache_stats` returns context_cache size

**SecurityTypeCacheAdapter:**
10. `clear_cache` calls both `clear_cache()` and `clear_cash_mappings_cache()`

**FMPCacheAdapter:**
11. `get_cache_stats` returns aggregated hit_rate + per-function details
12. `clear_cache` calls `cache_clear()` on all 5 functions

**IBKRDiskCacheAdapter (using `tmp_path`):**
13. `disk_cache_stats()` on empty dir → file_count=0
14. `disk_cache_stats()` with files → correct count/size/timestamps
15. `clear_disk_cache()` removes all files
16. `clear_disk_cache(older_than_hours=N)` only removes old files
17. `clear_disk_cache(older_than_hours=-1)` raises ValueError
18. Per-file OSError handling (corrupt/locked file skipped, reported in errors list)

**Failure paths:**
19. `SecurityTypeCacheAdapter.clear_cache()` raises on status=error dict
20. `CacheManager.clear_all()` reports per-cache failures (one fails, others succeed)
21. `CacheManager.get_all_stats_safe()` returns error dict for broken cache, others unaffected
22. `CacheManager.get_all_health_safe()` returns status=error for broken cache

**ServiceManager integration:**
23. `ServiceManager.clear_all_caches()` still works (backward compat)
24. `ServiceManager.health_check()` includes top-level `cache_enabled` key
25. `ServiceManager.clear_all_caches()` logs warning on partial failure

**CLI smoke tests (mock `build_cache_manager`):**
26. `list` subcommand prints cache names
27. `stats` subcommand prints stats
28. `clear` subcommand calls clear_all
29. `clear ibkr_disk --age 24` uses `clear_by_age()`

---

## Caches Registered (10 total)

| Name | Type | Adapter |
|------|------|---------|
| portfolio_service | TTLCache | ServiceCacheAdapter |
| optimization_service | TTLCache | ServiceCacheAdapter |
| stock_service | TTLCache | ServiceCacheAdapter |
| scenario_service | TTLCache | ServiceCacheAdapter |
| factor_intelligence_service | TTLCache | ServiceCacheAdapter (synthesized health) |
| returns_service | TTLCache | ServiceCacheAdapter |
| context_service | TTLCache | ContextCacheAdapter (synthesized stats/health) |
| security_type_service | static+DB | SecurityTypeCacheAdapter (dual clear) |
| fmp_lru | @lru_cache x5 | FMPCacheAdapter |
| ibkr_disk | parquet files | IBKRDiskCacheAdapter |

## Implementation Order

1. `services/cache_control.py` + `services/cache_adapters.py` (core, no deps)
2. `ibkr/cache.py` additions (disk stats + clear with error handling)
3. `run_cache.py` CLI (depends on 1+2)
4. `services/service_manager.py` update (depends on 1)
5. `tests/services/test_cache_control.py`

## Verification

1. `python run_cache.py list` — shows 10 caches
2. `python run_cache.py stats` — shows stats for all
3. `python run_cache.py stats ibkr_disk` — shows file count and size
4. `python run_cache.py clear ibkr_disk --age 72` — clears old files
5. `python run_cache.py health` — all show healthy/ok
6. `python -m pytest tests/services/test_cache_control.py -v` — all pass

## Codex Review Log

### Round 1 feedback (10 items) — all addressed:
1. **HIGH — Service method gaps**: Added `ContextCacheAdapter` (synthesizes stats/health), `ServiceCacheAdapter` fallback for missing `health_check`
2. **HIGH — Admin endpoint schemas**: Deferred admin endpoint changes (out of scope — needs live instance injection)
3. **HIGH — Fresh instances vs live**: Clarified: CLI uses `build_cache_manager()` (fresh), ServiceManager uses `_get_cache_manager()` (live instances)
4. **HIGH — Destructive scope**: Each cache is targeted individually; `clear_all` documents that it includes DB (SecurityType) and disk (IBKR)
5. **MED — ServiceManager health regression**: Preserves top-level `cache_enabled` key
6. **MED — SecurityType dual caches**: `SecurityTypeCacheAdapter.clear_cache()` calls both `clear_cache()` and `clear_cash_mappings_cache()`
7. **MED — Missing caches**: Explicitly scoped: IBKR config loaders (maxsize=1 YAML) excluded; `core/factor_intelligence.py` data loaders excluded from this phase
8. **MED — IBKR error handling**: Per-file try/except with `errors` list in return, `older_than_hours >= 0` validation
9. **LOW — FMP function signatures**: Corrected in plan
10. **MED — Test coverage gaps**: Added ServiceManager backward compat tests (#19-20), SecurityType dual-clear test (#10), error handling test (#18)

### Round 2 feedback (6 items) — all addressed:
1. **HIGH — Silent clear failures**: `SecurityTypeCacheAdapter` checks status dict, raises `RuntimeError` on error. `ServiceManager.clear_all_caches()` logs warnings on failures.
2. **MED — Protocol contract inconsistency**: `IBKRDiskCacheAdapter.clear_cache()` now takes no args (protocol-compliant). Added `clear_by_age()` as IBKR-specific method. CLI casts explicitly.
3. **MED — Stats/health fault isolation**: Added `get_all_stats_safe()` and `get_all_health_safe()` with per-cache try/except. CLI uses safe variants.
4. **LOW — FMP signatures**: Corrected to match actual code (`ticker, fmp_symbol, start_date, end_date`, `maturity, start_date, end_date`).
5. **LOW — core/factor_intelligence exclusion**: Reworded to "excluded from this phase" with accurate rationale.
6. **MED — Missing failure-path tests**: Added tests #19-22 for SecurityType error status, partial failure, safe stats/health resilience.
