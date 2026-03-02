# Fix Circular Imports: Extract Rate Limiter + Delete Dead Claude Route

## Context

`routes/factor_intelligence.py` does `from app import limiter` at module level (line 37). When imported standalone (e.g., in tests), this triggers loading all of `app.py`, which then imports the route file back — circular import:

```
$ python3 -c "from routes.factor_intelligence import factor_intelligence_router"
FAIL: cannot import name 'factor_intelligence_router' from partially initialized module
```

The app works in production only because `limiter` (line 973) is defined before route imports (line 4462). But standalone imports and tests break.

Additionally, `routes/claude.py` is dead code — the gateway channel replaced it, it imports a missing module (`services.claude.chat_service`), and it's not registered in app.py. Should be deleted.

Follows the proven pattern from `utils/response_model.py` (app.py line 128: "Extracted to break circular import app ↔ routes.plaid").

## Implementation

### 1. Create `utils/rate_limiter.py`

Extract from `app.py`:
- `VALID_KEYS`, `TIER_MAP`, `DEFAULT_KEYS`, `PUBLIC_KEY` (lines 755-769)
- `IS_DEV` flag (line 952)
- `get_rate_limit_key()` function (lines 954-971)
- `limiter = Limiter(key_func=get_rate_limit_key)` (line 973)

Dependencies: `slowapi.Limiter`, `slowapi.util.get_remote_address`, `fastapi.Request`, `os`

All internal references (`get_rate_limit_key` → `PUBLIC_KEY`, `TIER_MAP`, `IS_DEV`) move together.

### 2. Update `app.py`

Replace the extracted code blocks with:
```python
from utils.rate_limiter import limiter, TIER_MAP, PUBLIC_KEY, VALID_KEYS, DEFAULT_KEYS, IS_DEV
app.state.limiter = limiter
```

**Keep in app.py** (they reference `app`):
- `@app.exception_handler(RateLimitExceeded)` handler (line 978)
- `app.state.limiter = limiter` assignment

**20+ references to `TIER_MAP`/`PUBLIC_KEY`/`VALID_KEYS`/`IS_DEV` throughout app.py** continue working via the import — no changes needed to those call sites.

15 `@limiter.limit(...)` decorators inside app.py also continue working unchanged.

### 3. Update `routes/factor_intelligence.py`

Line 37: `from app import limiter` → `from utils.rate_limiter import limiter`

### 4. Delete `routes/claude.py`

Dead code:
- Imports missing `services.claude.chat_service.ClaudeChatService` (line 25)
- NOT registered in app.py (no `include_router`)
- Replaced by gateway channel (`routes/gateway_proxy.py`)
- Has its own `from app import limiter` circular import (line 151)

Also `git rm` it from staging (it's currently `A` staged).

## Files Modified

| File | Change |
|------|--------|
| `utils/rate_limiter.py` | **New**: `limiter`, `TIER_MAP`, `PUBLIC_KEY`, `VALID_KEYS`, `DEFAULT_KEYS`, `IS_DEV`, `get_rate_limit_key()` |
| `app.py` | Replace inline definitions (lines 755-769, 952-974) with import from `utils/rate_limiter` |
| `routes/factor_intelligence.py` | Line 37: import from `utils.rate_limiter` instead of `app` |
| `routes/claude.py` | **Delete** (dead code, replaced by gateway) |

## Verification

1. `python3 -c "from routes.factor_intelligence import factor_intelligence_router; print('OK')"` — standalone import succeeds (currently fails)
2. `python3 -c "from app import app; print(len(app.routes), 'routes')"` — still loads all routes
3. `python3 -c "from utils.rate_limiter import limiter; print(type(limiter))"` — standalone import works
4. `python3 -m pytest tests/factor_intelligence/ -x -q` — existing tests pass
5. `python3 -m pytest tests/api/ -x -q` — API tests pass
