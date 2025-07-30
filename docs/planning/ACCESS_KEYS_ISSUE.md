Current situation  
-----------------
`app.py` still defines:

```python
VALID_KEYS = set()   # line ~159
TIER_MAP   = {}      # line ~160
```

These are:

1. Mutable (they change at runtime).  
2. Process-local (each Gunicorn / uWSGI worker has its own copy).  
3. Unprotected (no lock, no persistence).

Why that’s risky  
----------------
• **Race conditions** – two threads could add/read simultaneously; you might drop an insertion or read a half-written value.  
• **Inconsistent view across workers** – a key generated in worker A isn’t visible in worker B.  
• **No durability** – server restart flushes the data.  
• **Hard to audit** – no central source for rate-limit counts, key revocation, or tier upgrades.

Ideal architecture  
------------------

1. Persist API keys (and their tier) in a **shared store**  
   a) Database table  
   ```sql
   CREATE TABLE api_keys (
       key       VARCHAR PRIMARY KEY,
       tier      VARCHAR NOT NULL DEFAULT 'public',
       created_at TIMESTAMPTZ DEFAULT now(),
       revoked   BOOLEAN DEFAULT FALSE
   );
   ```  
   b) or Redis:  
   ```
   SADD valid_keys <key>
   HSET tier_map <key> registered
   ```

2. Wrap access in a tiny helper module (`api_key_store.py`):

```python
def is_valid(key: str) -> bool: ...
def get_tier(key: str) -> str: ...
def add_key(key: str, tier: str = "registered"): ...
def revoke_key(key: str): ...
```

3. Add an **LRU/TTL read-through cache** in the helper so most requests stay in RAM:

```python
from cachetools import TTLCache
_CACHE = TTLCache(maxsize=10_000, ttl=60)  # 1-min freshness

def _get(key):
    if key in _CACHE:
        return _CACHE[key]
    row = db.fetch_row(...)        # or redis.hget(...)
    _CACHE[key] = row
    return row
```

4. Replace every direct reference in `routes/admin.py`, `routes/api.py`, etc. with calls to `api_key_store`.

5. Delete `VALID_KEYS` and `TIER_MAP` from `app.py`; tests can seed the store directly.

Transitional “quick fix” (dev only)  
-----------------------------------
If you’re not ready to add Redis/DB logic, you can still make them safe:

```python
VALID_KEYS_LOCK = threading.Lock()
TIER_MAP_LOCK   = threading.Lock()

with VALID_KEYS_LOCK:
    VALID_KEYS.add(new_key)

with TIER_MAP_LOCK:
    TIER_MAP[key] = tier
```

But remember this remains per-worker and non-durable—fine for local dev, inadequate for production.

Summary action list  
-------------------
1. Create `api_key_store.py` backed by Postgres (or Redis).  
2. Refactor code that mutates/reads `VALID_KEYS` / `TIER_MAP` to use the store.  
3. Remove the global sets from `app.py`.  
4. Optionally add Prometheus metrics: total keys, revoked keys, tier distribution.