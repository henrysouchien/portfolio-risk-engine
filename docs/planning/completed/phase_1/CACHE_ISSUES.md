PORTFOLIO CONTEXT BACKGROUND:

For multi-user caching: 

### User-Specific Caching Implementation
To make caching user-specific, use a dict (or Redis) with keys like `{user_id}:{input_hash}`. This isolates data and prevents most multi-user issues.

#### Step 1: Add Cache Manager to app.py (after imports, e.g., line 24)
import hashlib
from datetime import datetime, timedelta
import threading

user_caches = {}  # {user_key: result}
cache_lock = threading.Lock()
TTL = timedelta(minutes=30)

def get_user_cache_key(user_id: str, inputs: dict) -> str:
    input_hash = hashlib.sha256(str(inputs).encode()).hexdigest()
    return f"{user_id}:{input_hash}"

def cache_result(user_id: str, inputs: dict, compute_func, *args, **kwargs):
    key = get_user_cache_key(user_id, inputs)
    with cache_lock:
        if key in user_caches and datetime.now() < user_caches[key]['expiry']:
            return user_caches[key]['result']
        
        result = compute_func(*args, **kwargs)
        user_caches[key] = {'result': result, 'expiry': datetime.now() + TTL}
        return result

#### Step 2: Use in Services (e.g., PortfolioContextService)
# In get_context() or similar:
user_id = get_current_user()['id']
cached_result = cache_result(user_id, {'weights': weights, 'dates': (start, end)}, build_portfolio_view, weights=weights, ...)

#### Step 3: Clear on Events
def clear_user_cache(user_id: str):
    with cache_lock:
        user_caches = {k: v for k, v in user_caches.items() if not k.startswith(f"{user_id}:")}

# Call on logout or config change in routes/auth.py

BACKGROUND:

Hey, great question—this gets right to the heart of scaling computational caching (like the risk calcs in your backend, e.g., beta computations or portfolio views in `portfolio_optimizer.py` and `portfolio_risk.py`) for a multi-user environment. Right now, your backend caching is mostly global and input-agnostic (e.g., tied to file mod times in `app.py`), which works for single-user/single-computation scenarios but doesn't handle multiple users safely. Turning it multi-user involves **keying the cache by user-specific identifiers** plus the computation's unique inputs, ensuring isolation, thread-safety, and efficiency.

I'll explain the "how" step-by-step, with examples from your codebase, and propose a concrete implementation you can adapt (e.g., paste into `CACHE_ISSUES.md` around your cursor on line 5, since it's open). This builds on our earlier refactors—focusing on computational aspects like caching results of functions such as `solve_min_variance_with_risk_limits()` or `build_portfolio_view()`.

### Step 1: Understand the Current Setup (Single-User Computational Caching)
- Your backend caches results of heavy computations (e.g., factor betas, volatility, optimizations) to avoid recomputing on every call. For example:
  - In `app.py` (e.g., lines 488-509), `get_cached_portfolio_context()` caches the output of `get_portfolio_context()`, which runs calcs like `run_risk_score_analysis()` or `build_portfolio_view()`.
  - It's "keyed" implicitly by `portfolio.yaml`'s mod time— if unchanged, reuse the result.
- This is efficient for repeated identical computations but assumes a single context (no user differentiation). In multi-user, it fails because User A's calc could overwrite User B's.

### Step 2: Key Principles for Multi-User Caching
To make it multi-user:
- **User Scoping**: Always include a user identifier (e.g., `user_id` from sessions/OAuth) in the cache key. This isolates data—each user gets their own "slot."
- **Computation Fingerprinting**: Add a unique hash of the inputs (e.g., portfolio weights, dates, risk config) to the key. This ensures caches are specific to the exact calc (e.g., different portfolios get different entries, even for the same user).
- **Thread-Safety & Eviction**: Use locks for access, and add TTL (time-to-live) or size limits to evict old entries (prevents memory leaks under high load).
- **Storage**: Start with an in-memory dict (simple), then upgrade to Redis (already imported in `app.py` line 17) for persistence across processes/restarts.
- **Invalidation**: Provide ways to clear per-user (e.g., on logout/config change) or globally (e.g., market data update).

**Benefits**:
- **Isolation**: No leakage—User A can't see User B's cached betas.
- **Efficiency**: Still avoids recomputes for the same user/input.
- **Scalability**: Handles "lots of API calls" by distributing across keys.

**Tradeoffs**:
- More memory use (one entry per user/computation).
- Need to handle key collisions (rare with good hashing).
- If computations are *very* unique (e.g., per-request tweaks), cache hits drop—profile to confirm.

### Step 3: How to Implement It (Code Examples)
Use a cache dict (or Redis) with composite keys like `f"{user_id}:{input_hash}"`. Here's how to apply this to your backend:

#### Example: Basic In-Memory Multi-User Cache
Add this to `app.py` (e.g., after imports around line 24) for a global cache manager. It wraps computational functions (e.g., integrate with `PortfolioContextService` on line 232).

```24:24:app.py
# After existing imports (line 24)
import hashlib
from datetime import datetime, timedelta
from functools import wraps
import threading

# Multi-user cache setup
computation_cache = {}  # {key: {'result': any, 'expiry': datetime}}
cache_lock = threading.Lock()  # For thread-safety
DEFAULT_TTL = timedelta(minutes=30)

def get_cache_key(user_id: str, inputs: Dict) -> str:
    """Generate unique key: user_id + hash of inputs."""
    input_str = str(sorted(inputs.items()))  # Serialize inputs (e.g., weights, dates)
    input_hash = hashlib.sha256(input_str.encode()).hexdigest()
    return f"{user_id}:{input_hash}"

def cached_computation(ttl=DEFAULT_TTL):
    """Decorator for multi-user caching of computations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, user_id: str, **kwargs):
            inputs = kwargs.copy()  # Or extract from args if needed
            key = get_cache_key(user_id, inputs)
            
            with cache_lock:
                now = datetime.now()
                if key in computation_cache and computation_cache[key]['expiry'] > now:
                    return computation_cache[key]['result']
                
                # Compute and cache
                result = func(*args, **kwargs)
                computation_cache[key] = {'result': result, 'expiry': now + ttl}
                return result
        return wrapper
    return decorator

# Example: Clear cache for a user (e.g., on logout)
def clear_user_cache(user_id: str):
    with cache_lock:
        keys_to_delete = [k for k in computation_cache if k.startswith(f"{user_id}:")]
        for k in keys_to_delete:
            del computation_cache[k]
```

#### Applying to a Computational Function
For something like `build_portfolio_view()` (from `portfolio_risk.py`, used in caching), decorate it and pass `user_id`:

```1:1:portfolio_risk.py
@cached_computation()
def build_portfolio_view(weights: Dict, start_date: str, end_date: str, expected_returns: Optional[Dict], stock_factor_proxies: Dict, user_id: str) -> Dict:
    # Existing computation logic...
    # (Add user_id to function sig if not already)
```

- **In API Routes**: In `routes/api.py`, extract `user_id` from session (via `get_current_user()` from `app.py` line 345) and pass to cached functions.
- **Upgrading to Redis**: Replace the dict with Redis ops (e.g., `redis_client.get(key)`, `redis_client.set(key, result, ex=TTL_seconds)`). This handles multi-process (e.g., Gunicorn) and persistence.

#### Integration with Your Codebase
- Tie into `PortfolioContextService` (app.py line 232): Add a method like `get_cached_result(user_id, func, **kwargs)` that uses the decorator.
- For `utils/portfolio_context.py`: As we refactored before, make instances per-user and cache metadata inside them (already user-scoped).
- Invalidation: Call `clear_user_cache(user_id)` on events like logout (in `routes/auth.py`) or config updates.

This turns single-user computational caching into multi-user by scoping via keys—efficient and safe. Profile with tools like `cProfile` to measure hit rates. If you want me to apply this edit to a file (e.g., `app.py`) or expand the example, let me know! How does this fit with your caching needs? 🚀




For the portfolio_context:

Yes, you're spot on—`utils/portfolio_context.py` is indeed one of the biggest potential issues in terms of global state and caching, especially in a multi-user context. It's more directly problematic than the globals in `app.py` (like `portfolio_context_cache`) because it explicitly deals with user-specific data (e.g., `user_id` and position metadata) but uses a shared global singleton. This could lead to data leakage or corruption across users/requests, even if portfolios are unique. 

Let me explain why it's a standout concern and propose a targeted refactor to fix it. Since you have `app.py` open (cursor on line 24, near imports), I'll also note how this ties in and suggest minimal changes there for integration.

If this aligns with what you meant, I can apply the edit directly using tools—or if you want to tweak the proposal, let me know!

### Why `portfolio_context.py` Is the Biggest Potential Issue
- **The Core Problem**: This file implements a classic singleton pattern (lines 7-57), with a global instance `portfolio_context = PortfolioContext()` on line 57. It's thread-safe for *creation* (via double-checked locking on lines 13-19), but the state (e.g., `self.user_id`, `self.portfolio_name`, and the cached `self.position_metadata`) is shared globally across all threads/requests/users.
  - When `set_context()` (lines 28-33) is called (e.g., during a user session), it overwrites the shared state. If another user's request interrupts, their data could mix in (e.g., User A's metadata gets served to User B).
  - The lazy caching in `get_metadata()` (lines 35-47) loads and stores user-specific data (via `get_position_metadata()` on line 41), but since it's global, it's not isolated. Clearing only happens on context change (line 32, near where your cursor might be if you're looking at this file), but that's not foolproof in concurrent scenarios.
  
- **Why "Biggest" Compared to `app.py` Globals**:
  - `app.py`'s `portfolio_context_cache` is more generic (caches overall portfolio views based on file mod times) and could be "OK" with unique portfolios, as you noted. But `portfolio_context.py` is tightly coupled to *user identities* (stores `user_id` explicitly), making leaks more dangerous (e.g., privacy risks if metadata includes sensitive position details).
  - It's used in user-facing flows (e.g., integrated with `PortfolioContextService` in `services/portfolio/context_service.py`, which is instantiated in `app.py` on line 232), so issues would affect core features like display formatting.
  - No per-method locking beyond init—unlike `app.py`'s `pipeline_lock` (line 225), this lacks protection for reads/writes, amplifying race condition risks in Flask's threaded environment.

- **When It Bites**: Fine in single-user dev, but in prod with concurrent users (e.g., via API routes), it could cause inconsistent or leaked data. If deployed multi-process (e.g., Gunicorn), each process has its own singleton, leading to inconsistencies.

PORTFOLIO CACHE FIX:

### Recommended Fix: Refactor to Per-User Instances (No More Singleton/Global)
To eliminate the global sharing, we can refactor `PortfolioContext` from a singleton to a regular class. Instantiate it per-user (e.g., in a service or request context), so each user gets their own isolated instance. This removes the global entirely, scopes caching to the user, and integrates nicely with the app's service layer.

- **Benefits**: Full isolation, no globals, easy to test/mock. Keeps lazy caching but makes it per-user.
- **Minimal Impact**: No changes needed to callers if we wrap it in a service (e.g., `PortfolioContextService` can manage instances).
- **Tie-In to `app.py`**: Since `app.py` already has `portfolio_service = PortfolioContextService()` (line 232), we can expand that service to hold a dict of per-user contexts (e.g., `{user_id: PortfolioContext()}`). Add an import for the refactored class around your cursor (after line 24).

Here's the proposed edit to `utils/portfolio_context.py`. It removes the singleton logic (lines 10-19, 57), turns it into a plain class, and adds a simple TTL for cache expiration (to prevent staleness). Apply this to the whole file for a clean refactor.


```typescript

utils/portfolio_context.py

"""Portfolio context management for display formatting."""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import threading  # Keep for potential future use, but not needed now

class PortfolioContext:
    """User-scoped context for active portfolio metadata (non-singleton)."""
    
    def __init__(self, user_id: int, portfolio_name: str):
        self.user_id = user_id
        self.portfolio_name = portfolio_name
        self.position_metadata: Optional[Dict[str, Dict[str, str]]] = None
        self.metadata_timestamp: Optional[datetime] = None
        self.ttl = timedelta(minutes=30)  # Cache expiration (configurable)
    
    def set_context(self, user_id: int, portfolio_name: str):
        """Set the active portfolio context."""
        self.user_id = user_id
        self.portfolio_name = portfolio_name
        # Clear cached metadata when context changes
        self.position_metadata = None
        self.metadata_timestamp = None
    
    def get_metadata(self) -> Optional[Dict[str, Dict[str, str]]]:
        """Get position metadata for active portfolio with TTL check."""
        now = datetime.now()
        if self.position_metadata and self.metadata_timestamp and (now - self.metadata_timestamp) < self.ttl:
            return self.position_metadata
        
        if self.user_id and self.portfolio_name:
            # Lazy load metadata
            try:
                from position_metadata import get_position_metadata
                self.position_metadata = get_position_metadata(
                    self.user_id, self.portfolio_name
                )
                self.metadata_timestamp = now
            except Exception:
                # Fallback to empty metadata
                self.position_metadata = {}
                self.metadata_timestamp = now  # Still timestamp for TTL
        return self.position_metadata
    
    def clear(self):
        """Clear the context."""
        self.user_id = None
        self.portfolio_name = None
        self.position_metadata = None
        self.metadata_timestamp = None
```

**Instructions for the Edit**: 
- This replaces the entire file content. Now, to use it, instantiate per-user (e.g., in `PortfolioContextService`): `self.contexts[user_id] = PortfolioContext(user_id, portfolio_name)`.
- In `app.py`, add an import after line 24: `from utils.portfolio_context import PortfolioContext`. Then, in the service (or routes), create instances as needed instead of relying on the global.

This makes it user-aware and eliminates the global. Test by simulating multi-user requests (e.g., via Postman) to ensure isolation. If you want to add locking (e.g., a per-instance lock) or integrate with Redis, we can build on this. What's your take—ready to apply, or iterate? 🚀




