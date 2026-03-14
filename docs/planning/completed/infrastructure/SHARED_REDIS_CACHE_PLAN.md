# Shared Redis Cache for Multi-Worker Uvicorn

**Date:** 2026-03-05
**Status:** Planning

## Context

Dev runs with `--workers 2`. Each worker has its own in-memory TTLCache (500 entries, 30min TTL). The most expensive computation — `PortfolioService.analyze_portfolio()` — takes 30-60s cold. If requests hit different workers, the same analysis runs twice. Redis is already in `requirements.txt` and imported (unused) in `app.py`.

**Goal:** Share `PortfolioService` analysis results across workers via Redis as an L2 cache layer, behind a feature flag (off by default).

---

## Architecture

```
analyze_portfolio() called
  → L1 check (per-worker TTLCache) → hit? return RiskAnalysisResult
  → L2 check (Redis, pickle+zlib) → hit? store in L1, return RiskAnalysisResult
  → compute (30-60s) → store in L1 + L2, return RiskAnalysisResult
```

Write-through: every L1 write also writes to L2. L2 hits warm L1 for subsequent same-worker requests.

**Serialization:** pickle protocol 5 + zlib level 1. Typical `RiskAnalysisResult` ~200-400KB raw → ~50-100KB compressed. Roundtrip ~5-10ms vs 30-60s recompute. Safe for same-version workers with 30min TTL. Deserialization failures → treat as cache miss.

---

## Phase 1: Config (4 env vars)

**File:** `utils/config.py` — add after line ~77 (existing cache settings block):

```python
# === Redis L2 Cache Settings ===
REDIS_CACHE_ENABLED = os.getenv("REDIS_CACHE_ENABLED", "false").strip().lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL", str(SERVICE_CACHE_TTL)))
REDIS_CACHE_KEY_PREFIX = os.getenv("REDIS_CACHE_KEY_PREFIX", "risk:v1:")
```

The `v1:` prefix is a version namespace — bump to `v2:` if `RiskAnalysisResult` shape changes.

---

## Phase 2: Redis Cache Client (~100 lines)

**New file:** `services/redis_cache.py`

`RedisCache` class:
- `__init__(url, ttl, prefix)` — `redis.Redis.from_url(url)` with default connection pooling
- `get(key) → object | None` — `redis.get(prefix+key)` → `zlib.decompress` → `pickle.loads`
- `set(key, value)` — `pickle.dumps(value, protocol=5)` → `zlib.compress(level=1)` → `redis.setex(prefix+key, ttl, compressed)`
- `flush_prefix()` — `SCAN` + `DELETE` all keys matching prefix
- `health_check() → dict` — `redis.ping()`, key count, memory info

**Graceful fallback:** All methods wrap in `try/except Exception` → log warning, return `None`. If Redis is down, system operates exactly as today (L1 only).

Module-level `get_redis_cache() → RedisCache | None` singleton factory — returns `None` when `REDIS_CACHE_ENABLED=false` or connection fails at init.

---

## Phase 3: Integrate into PortfolioService (~25 lines)

**File:** `services/portfolio_service.py`

### 3a. Lazy Redis property

In `__init__` (line ~100), after `self._init_service_cache()`:
```python
self._redis_cache = None  # lazy init
```

New property:
```python
@property
def _redis(self):
    if self._redis_cache is None:
        from services.redis_cache import get_redis_cache
        self._redis_cache = get_redis_cache() or False  # False = checked, unavailable
    return self._redis_cache or None
```

### 3b. L2 check after L1 miss

Insert after the L1 cache check block (after line ~256, where the `with self._lock` block exits without returning):

```python
# L2 check (Redis)
if self._redis and self.cache_results:
    l2_result = self._redis.get(cache_key)
    if l2_result is not None and hasattr(l2_result, 'to_api_response'):
        portfolio_logger.info("Redis L2 cache hit: %s", cache_key[:40])
        with self._lock:
            self._cache[cache_key] = l2_result  # warm L1
        return l2_result
```

### 3c. Write-through after L1 store

Insert after L1 cache store (after line ~344):

```python
# Write-through to L2
if self._redis and self.cache_results:
    self._redis.set(cache_key, result)
```

### 3d. Extend `clear_cache()` to flush L2

Add to `clear_cache()`:
```python
if self._redis:
    self._redis.flush_prefix()
```

---

## Phase 4: CacheManager Integration (~30 lines)

**File:** `services/cache_adapters.py` — add `RedisCacheAdapter` matching existing adapter contract (`cache_enabled`, `cache_size` keys):

```python
class RedisCacheAdapter:
    cache_name = "redis_l2"

    def clear_cache(self):
        from services.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if cache:
            cache.flush_prefix()

    def get_cache_stats(self):
        from services.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if not cache:
            return {"cache_enabled": False, "cache_size": 0}
        info = cache.health_check()
        return {"cache_enabled": True, "cache_size": info.get("key_count", 0), **info}

    def health_check(self):
        from services.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if not cache:
            return {"status": "disabled"}
        info = cache.health_check()
        return {"status": "healthy" if info.get("connected") else "unavailable", **info}
```

**File:** `services/cache_control.py` — register in `build_cache_manager()` (line ~136, before `return manager`):

```python
from services.cache_adapters import RedisCacheAdapter
manager.register(RedisCacheAdapter())
```

**File:** `services/service_manager.py` — register in `_get_cache_manager()` (line ~136, before `self._cache_manager = cm`):

```python
from services.cache_adapters import RedisCacheAdapter
cm.register(RedisCacheAdapter())
```

---

## Feature Flag Behavior

| `REDIS_CACHE_ENABLED` | Redis reachable | Behavior |
|---|---|---|
| `false` (default) | N/A | Current behavior, no Redis code runs |
| `true` | Yes | L1 + L2 write-through |
| `true` | No | L1 only, warning at startup |
| `true` | Intermittent | L1 only per failed op, warning logged |

---

## Security Note

Redis must run on localhost (dev) or a private/trusted network (prod). `pickle.loads` is used for deserialization — this is safe within a trusted boundary (same trust model as in-process TTLCache). Do not expose the Redis instance to untrusted networks. For production, use Redis AUTH and bind to private IPs.

---

## Scope Boundaries

- **Only** PortfolioService gets Redis — highest value target (30-60s compute). Extend to other services later based on observed hit rates.
- **No** pub/sub for cross-worker invalidation — TTL expiry sufficient for 30min caches.
- **No** changes to `ServiceCacheMixin` interface — Redis added directly to PortfolioService.
- **No** single-flight / distributed lock — with 2 workers and 1 user, simultaneous same-key misses are rare. Worst case: both workers compute (same as today). Add if scaling beyond 2 workers.
- Cache keys already include user_id via `PortfolioData.get_cache_key()` — no key changes needed.

---

## Files Modified

| File | Change |
|------|--------|
| `utils/config.py` | +4 lines — env var constants |
| `services/redis_cache.py` | NEW ~100 lines — Redis L2 client |
| `services/portfolio_service.py` | +25 lines — L2 check, write-through, clear |
| `services/cache_adapters.py` | +25 lines — RedisCacheAdapter |
| `services/cache_control.py` | +2 lines — register adapter |
| `services/service_manager.py` | +2 lines — register adapter in live path |

---

## Local Dev Setup

```bash
docker run -d -p 6379:6379 --name redis-dev redis
```

Add to `.env`:
```
REDIS_CACHE_ENABLED=true
REDIS_URL=redis://localhost:6379/0
```

---

## Verification

1. `python -m pytest tests/` — all existing tests pass (feature flag off by default)
2. `REDIS_CACHE_ENABLED=true make dev` → hit `/api/portfolio-analysis` twice → second request log shows "Redis L2 cache hit"
3. Two-worker test: kill one worker, restart → second worker picks up cached result from Redis
4. Redis down test: stop Redis container → requests still work via L1 only, warning in logs

## Reference Files

- `services/cache_mixin.py` — ServiceCacheMixin (L1 TTLCache bootstrap)
- `services/cache_control.py` — CacheManager + `build_cache_manager()` factory
- `services/cache_adapters.py` — Existing cache adapters (6 types)
- `services/portfolio_service.py` — PortfolioService.analyze_portfolio() (lines 106-351)
- `utils/config.py` — Existing cache config constants (lines 73-77)
