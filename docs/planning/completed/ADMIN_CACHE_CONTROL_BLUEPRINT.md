# Centralized Admin Cache Control — Blueprint

> **Status:** ✅ IMPLEMENTED (backend + CLI) — see `docs/planning/completed/CACHE_CONTROL_PLAN.md`
> Formal `CacheControl` Protocol, `CacheManager` registry, 6 adapters (11 caches), `run_cache.py` CLI.
> Remaining from this blueprint: admin UI (React), dry_run mode, per-user scoped clear, audit logging — tracked separately.

## Executive Summary

Create a centralized, safe, and observable cache control surface that lets admin users inspect, clear, and monitor backend caches (per service and globally) without server restarts. The system standardizes how caches are registered, exposed, and audited, while preserving per‑user isolation where applicable.

## Goals

- Single, consistent admin entry point to:
  - View cache health and stats across services
  - Clear caches (global, per‑service, or scoped by user/portfolio where applicable)
  - Monitor cache hit/miss metrics and TTL configuration
- Minimize risk (role‑based access, audit logs, dry‑runs)
- Keep implementation lightweight and backward‑compatible

## Non‑Goals

- Replacing existing in‑service caches (we wrap and expose)
- Changing cache implementations (TTLCache, disk, Redis, etc.)
- Auto‑tuning cache sizes/TTLs (future enhancement)

---

## Architecture Overview

1. Registry Interface: A standard Python protocol for any service exposing cache control.
2. Service Implementations: PortfolioService, OptimizationService, ScenarioService, StockService, PortfolioContextService, etc., implement the interface.
3. Aggregator (CacheManager): Collects registered services and orchestrates bulk operations (stats/clear/health).
4. Admin API (FastAPI): Exposes endpoints under `/admin/cache/*` with RBAC and audit logging.
5. Admin UI: A single page with per‑service cards to view stats and clear caches.

```
Admin UI → Admin API → CacheManager → Registered Services → Caches
                      ↘ Metrics/Audit Logs ↙
```

---

## Interfaces

### Python Protocol (CacheControl)

```python
from typing import Protocol, Dict, Any

class CacheControl(Protocol):
    def clear_cache(self) -> None: ...
    def get_cache_stats(self) -> Dict[str, Any]: ...
    def health_check(self) -> Dict[str, Any]: ...
```

### Recommended `get_cache_stats()` shape

```json
{
  "cache_enabled": true,
  "processed_cache_size": 123,
  "ttl": 1800,
  "maxsize": 1000,
  "hit_rate": 0.82,
  "notes": "free‑form"
}
```

### Service Implementations

- PortfolioService (already has `clear_cache`, `get_cache_stats`, `health_check`).
- OptimizationService, ScenarioService, StockService
- PortfolioContextService (has `clear_cache(user_id?, portfolio_name?)` — expose both global and scoped variants)
- SecurityTypeService (if maintaining a DB/disk cache, provide a stub that reports stats)
- data_loader (disk cache): Expose a `DataLoaderCacheControl` that can remove parquet cache entries by key/prefix or entirely.

---

## Registration and Aggregation

### Service Registration

- A central `ServiceManager` (existing) adds a method like `get_registered_cache_controls()` returning `{ name: CacheControl }`.
- Alternatively, a dedicated `CacheRegistry` where each service registers itself during startup.

```python
# services/service_manager.py
class ServiceManager:
    def get_registered_cache_controls(self) -> Dict[str, CacheControl]:
        return {
            "portfolio_service": self.portfolio_service,
            "optimization_service": self.optimization_service,
            "scenario_service": self.scenario_service,
            "portfolio_context_service": self.portfolio_context_service,
            # "data_loader_cache": DataLoaderCacheControl(),
        }
```

### CacheManager

- Aggregator with bulk ops:

```python
class CacheManager:
    def __init__(self, registry: Dict[str, CacheControl]):
        self.registry = registry

    def clear_all(self):
        for name, svc in self.registry.items():
            svc.clear_cache()

    def stats_all(self) -> Dict[str, Dict[str, Any]]:
        return {name: svc.get_cache_stats() for name, svc in self.registry.items()}

    def health_all(self) -> Dict[str, Dict[str, Any]]:
        return {name: svc.health_check() for name, svc in self.registry.items()}
```

---

## Admin API (FastAPI)

### Endpoints (initial)

- GET `/admin/cache/stats` → all services’ stats
- GET `/admin/cache/health` → all services’ health
- POST `/admin/cache/clear` → clear all services (body: `{ dry_run?: bool }`)
- POST `/admin/cache/clear/{service}` → clear a specific service
- POST `/admin/cache/clear/context` → clear portfolio context cache (body: `{ user_id?: int, portfolio_name?: str }`)
- (Optional) GET `/admin/cache/dataloader/keys` and POST `/admin/cache/dataloader/clear` for disk cache

### Security

- Admin role required (reuse existing auth dependency).
- CSRF protection (if applicable for internal tools) or require POST with tokens.
- Rate limit admin endpoints to prevent abuse.

### Audit Logging

- Log every clear with: user_id, service(s), scope, dry_run flag, time, and result.
- Store structured JSON entries (existing `utils.logging` pipeline).

---

## UI Design (Admin Screen)

- A “Cache Control” page under Admin with:
  - Aggregate stats (total entries across services, last clear time)
  - Per‑service cards: name, size, health, TTL, hit‑rate (if tracked)
  - Actions: Clear service cache, Clear all caches
  - Scoped actions (when applicable): Clear Portfolio Context for user/portfolio
  - Confirm modals: “Are you sure? This may affect in‑progress requests.”
  - A “Dry‑run” checkbox for clear operations

---

## Cache Types and Considerations

- In‑memory TTL caches (ServiceCacheMixin): fast, per‑process
- Disk caches (data_loader parquet): persistent; allow clear by key/prefix/all
- Database caches (e.g., SecurityTypeService): prefer expiring by TTL policy; provide a maintenance endpoint to drop stale rows if necessary
- Redis (if used in future): add a RedisCacheControl wrapper

### Multi‑Tenant/Per‑User Isolation

- For per‑user caches (e.g., portfolio context), prefer scoped clear:
  - Clear by `user_id` and `portfolio_name` when provided
  - Fallback to global clear only for admin troubleshooting

### Safety & Rollback

- All clear endpoints support `dry_run` (no‑op, returns affected counts estimated if available)
- Feature flag: ENABLE_ADMIN_CACHE_CONTROL to disable routes in prod if necessary

---

## Metrics & Observability

- Per‑service metrics (expose via stats):
  - entries, maxsize, ttl, hit_rate (if measured), last_cleared_at
- Admin API logs: structured, searchable, with user attribution
- Dashboard: A simple chart/table for cache trends (optional)

---

## Testing Strategy

- Unit tests
  - CacheManager: clearing all services calls each `clear_cache()` once
  - Registry returns expected service names
- Integration tests
  - Admin API endpoints: RBAC, dry_run behavior, clear-specific service
  - PortfolioContextService: scoped clear tests for user/portfolio
- End‑to‑end (optional)
  - Admin UI flows: load stats → clear service → verify stats updated

---

## Rollout Plan

1. Phase 1 (Backend) — ✅ Core done (informal pattern)
   - ~~Implement CacheControl protocol and CacheManager~~ → Services implement methods directly; `ServiceManager` aggregates via `clear_all_caches()`, `get_cache_stats()`, `health_check()`
   - ✅ Core services registered: PortfolioService, OptimizationService, ScenarioService, StockService, FactorIntelligenceService, ReturnsService, PortfolioContextService
   - ✅ Admin endpoints: `GET /admin/cache_status`, `POST /admin/clear_cache` in `routes/admin.py`
   - ❌ Not yet: formal CacheControl protocol, per-service clear endpoint, dry_run, scoped context clear
2. Phase 2 (UI) — ❌ Not started
   - Build Admin UI page with stats and clear controls
   - Add confirm modals and dry‑run
3. Phase 3 (Enhancements) — ❌ Not started
   - Add data_loader disk cache controls (keys/prefix purge)
   - Track hit/miss metrics (if feasible)
   - Add feature flag for production rollout

---

## Open Questions / Decisions

- Do we want per‑user cache clear for PortfolioService (in‑memory TTL)?
  - Likely no (global per‑process cache); prefer portfolio context scoped clear.
- Should we add a Redis layer to centralize caches across processes?
  - Not in scope now; blueprint allows plugging a RedisCacheControl later.
- How strict should auth be? Dedicated admin role vs. ops role?
  - Recommend Admin role + audit logging.

---

## Appendix: Example FastAPI Snippets

```python
from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_admin
from services.service_manager import service_manager

router = APIRouter(prefix="/admin/cache", tags=["admin-cache"])

@router.get("/stats")
async def cache_stats(user=Depends(require_admin)):
    cm = service_manager.get_cache_manager()
    return cm.stats_all()

@router.get("/health")
async def cache_health(user=Depends(require_admin)):
    cm = service_manager.get_cache_manager()
    return cm.health_all()

@router.post("/clear")
async def cache_clear_all(dry_run: bool = False, user=Depends(require_admin)):
    cm = service_manager.get_cache_manager()
    if dry_run:
        return {"dry_run": True, "services": list(cm.registry.keys())}
    cm.clear_all()
    return {"cleared": list(cm.registry.keys())}

@router.post("/clear/{service}")
async def cache_clear_service(service: str, user=Depends(require_admin)):
    cm = service_manager.get_cache_manager()
    svc = cm.registry.get(service)
    if not svc:
        raise HTTPException(404, f"Unknown service: {service}")
    svc.clear_cache()
    return {"cleared": service}
```

---

## Appendix: Suggested Code Stubs (Non-Functional Placeholders)

These stubs can be added as internal modules to ease incremental wiring. They are no-ops until services are registered.

### cache_control.py

```python
from typing import Protocol, Dict, Any

class CacheControl(Protocol):
    def clear_cache(self) -> None: ...
    def get_cache_stats(self) -> Dict[str, Any]: ...
    def health_check(self) -> Dict[str, Any]: ...
```

### cache_manager.py

```python
from typing import Dict, Any
from .cache_control import CacheControl

class CacheManager:
    def __init__(self, registry: Dict[str, CacheControl] | None = None):
        self.registry: Dict[str, CacheControl] = registry or {}

    def register(self, name: str, service: CacheControl) -> None:
        self.registry[name] = service

    def clear_all(self) -> None:
        for svc in self.registry.values():
            svc.clear_cache()

    def clear(self, name: str) -> None:
        if name in self.registry:
            self.registry[name].clear_cache()

    def stats_all(self) -> Dict[str, Dict[str, Any]]:
        return {name: svc.get_cache_stats() for name, svc in self.registry.items()}

    def health_all(self) -> Dict[str, Dict[str, Any]]:
        return {name: svc.health_check() for name, svc in self.registry.items()}
```

### services/service_manager.py (integration stub)

```python
# from .portfolio_service import PortfolioService
# from .optimization_service import OptimizationService
# from .portfolio.context_service import PortfolioContextService
# from admin.cache_manager import CacheManager

class ServiceManager:
    def __init__(self, cache_results: bool = True):
        # self.portfolio_service = PortfolioService(cache_results=cache_results)
        # self.optimization_service = OptimizationService(cache_results=cache_results)
        # self.portfolio_context_service = PortfolioContextService()
        self._cache_manager = None

    def get_registered_cache_controls(self) -> dict:
        # Return only services available in this build; fill in as they land
        registry = {}
        # if hasattr(self, 'portfolio_service'):
        #     registry['portfolio_service'] = self.portfolio_service
        # if hasattr(self, 'optimization_service'):
        #     registry['optimization_service'] = self.optimization_service
        # if hasattr(self, 'portfolio_context_service'):
+        #     registry['portfolio_context_service'] = self.portfolio_context_service
        return registry

    def get_cache_manager(self):
        if self._cache_manager is None:
            from admin.cache_manager import CacheManager
            self._cache_manager = CacheManager(self.get_registered_cache_controls())
        return self._cache_manager
```

---

## Summary

This blueprint introduces a small, standardized layer to manage caches across services, safely and observably. It centralizes ops controls, keeps the implementation incremental, and sets the foundation for a richer admin experience (metrics, partial clears, dry‑runs) without disrupting existing service code.
