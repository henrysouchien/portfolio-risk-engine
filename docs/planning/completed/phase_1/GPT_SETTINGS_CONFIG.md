A simple yet future-proof pattern is to centralize all tunable flags in a single “settings” object that’s loaded once at start-up and can be overridden by environment variables (or a `.env` file).  Two lightweight ways to do this in Python:

--------------------------------------------------
1. Plain dataclass + environment overlay  
   *Zero external dependencies.*

```python
# utils/settings.py
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    # ───── Feature toggles ─────
    USE_GPT_SUBINDUSTRY: bool = (
        os.getenv("USE_GPT_SUBINDUSTRY", "true").lower() == "true"
    )
    # add other toggles here …

# single immutable instance that the whole app imports
settings = Settings()
```

Usage anywhere in the code-base:
```python
from utils.settings import settings

if settings.USE_GPT_SUBINDUSTRY:
    peers = get_subindustry_peers_from_ticker(ticker)
```

• Override at runtime with  
  `export USE_GPT_SUBINDUSTRY=false` (Docker env, Heroku config-var, .env, etc.)  
• Because `Settings` is frozen, values are effectively constants; tests can monkey-patch `settings.USE_GPT_SUBINDUSTRY` if needed.

--------------------------------------------------
2. Pydantic `BaseSettings` (adds validation & `.env` support)

```python
# utils/settings.py
from functools import lru_cache
from pydantic import BaseSettings

class Settings(BaseSettings):
    USE_GPT_SUBINDUSTRY: bool = True        # default

    class Config:
        env_file = ".env"                   # optional .env support
        env_prefix = ""                     # no prefix needed

@lru_cache
def get_settings() -> Settings:
    return Settings()                       # auto-reads env vars/.env
```

Usage:
```python
from utils.settings import get_settings

settings = get_settings()
if settings.USE_GPT_SUBINDUSTRY:
    ...
```

Advantages
-----------
• Single place to scan for all tunables (“self-documenting”).  
• Environment-first design—easy to switch per environment/container.  
• Immutable at runtime (via frozen dataclass or `lru_cache`).  
• No more scattering `allow_gpt=True` literals—modules just read the flag.  
• Extensible: add API keys, rate-limit thresholds, feature flags in one file.

Which to pick?
--------------
– If you want **zero dependencies**, go with the frozen dataclass.  
– If you already have or don’t mind adding **Pydantic**, its type-validation and `.env` parsing are very handy.

Either way, migrating is minimal:

1. Create `utils/settings.py` with one of the patterns above.  
2. Replace direct env-lookups & hard-coded toggles with `settings.USE_GPT_SUBINDUSTRY`.  
3. Remove explicit `allow_gpt=…` arguments where you want global behaviour (keep them in unit tests or special scripts).

Now the whole team (and your CI/CD) can turn GPT peer generation on/off with a single environment variable.