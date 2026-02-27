# FMP Data Abstraction Layer Design

> **Status: ✅ IMPLEMENTED**
>
> This layer has been implemented at `fmp/` (root level). During the modular architecture migration, it will be moved to `loaders/financial_data/fmp/`.
>
> **Current location:** `fmp/`
> **Target location:** `loaders/financial_data/fmp/`

## Overview

This document describes the design for a unified FMP (Financial Modeling Prep) data layer that makes FMP data easily discoverable and accessible, both for development and for AI-assisted analysis.

### Goals

1. **Discoverable** — Claude can read the module and understand what data is available
2. **Easy to extend** — adding new endpoints requires minimal boilerplate
3. **Built on existing infrastructure** — reuses caching, logging, error handling
4. **Backward compatible** — existing code continues to work during incremental migration
5. **MCP-ready** — structure can be converted to an MCP server if needed later
6. **Aligned with modular architecture** — fits into the Loaders layer per `MODULAR_ARCHITECTURE_REFACTOR_PLAN.md`

---

## Placement in Modular Architecture

Per the [Modular Architecture Refactor Plan](./planning/MODULAR_ARCHITECTURE_REFACTOR_PLAN.md), this layer belongs in the **Loaders** layer:

```
loaders/
├── plaid/                    # Brokerage positions
├── snaptrade/                # Brokerage positions
└── financial_data/           # Financial data APIs
    ├── fmp/                  # FMP abstraction layer ← THIS DESIGN
    │   ├── __init__.py
    │   ├── client.py
    │   ├── registry.py
    │   ├── cache.py
    │   └── exceptions.py
    └── data_loader.py        # Existing (migrates to use fmp/ internally)
```

**Why "financial_data" not "market_data":** FMP provides more than market prices — it includes fundamentals, analyst estimates, SEC filings, economic indicators, and more.

**Architecture alignment:**
- Loaders fetch external data → FMP layer fetches from FMP API
- Modules receive data, transform it → Modules consume DataFrames from FMP layer
- Modules don't know about persistence → FMP caching is internal, invisible to callers

---

## Current State

### Existing FMP Usage

The codebase currently accesses FMP via direct HTTP calls, primarily in `data_loader.py`:

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `fetch_monthly_close()` | `/stable/historical-price-eod/full` | Month-end close prices |
| `fetch_monthly_total_return_price()` | `/stable/historical-price-eod/dividend-adjusted` | Dividend-adjusted prices |
| `fetch_monthly_treasury_rates()` | `/stable/treasury-rates` | Treasury yields |
| `fetch_dividend_history()` | `/stable/dividends` | Dividend history |

Additionally, `utils/ticker_resolver.py` uses:
- `/api/v3/search` — Company search
- `/api/v3/profile/{symbol}` — Quote with currency

### Existing Infrastructure (to reuse)

- **API Key**: Loaded from `FMP_API_KEY` env var via `python-dotenv`
- **Disk Cache**: Parquet files with Zstandard compression, MD5-hashed keys
- **LRU Cache**: In-memory layer (configurable sizes in `utils/config.py`)
- **Error Handling**: Rate limit detection, fallback chains, health logging
- **Ticker Resolution**: International symbol mapping

### Current Gaps

- API key and BASE_URL duplicated across 3 modules
- No unified request client — direct `requests.get()` calls everywhere
- No endpoint registry or discoverability
- Only 4 of many available FMP endpoints implemented

---

## FMP API Breadth

FMP offers extensive data beyond what's currently used:

| Category | Examples |
|----------|----------|
| **Financial Statements** | Income statement, balance sheet, cash flow (quarterly/annual) |
| **Analyst Data** | Price targets, estimates, grades, consensus ratings |
| **Key Metrics** | Enterprise value, ratios, Altman Z-Score, owner earnings |
| **SEC Filings** | 8-K, 10-K, 10-Q, 13F institutional holdings |
| **Economic Data** | Treasury rates, GDP, unemployment, inflation |
| **Earnings & Events** | Transcripts, dividend calendar, IPOs, splits |
| **Market Performance** | Sector/industry performance, index constituents |
| **Alternative Assets** | ETF holdings, crypto, forex, commodities |

---

## Proposed Architecture

### Module Structure

```
risk_module/
├── loaders/
│   └── financial_data/           # Financial data APIs
│       ├── __init__.py           # Re-exports from fmp/
│       ├── fmp/                   # FMP abstraction package
│       │   ├── __init__.py       # Public API: FMPClient, fetch, get_client
│       │   ├── client.py         # FMPClient class
│       │   ├── registry.py       # Endpoint definitions with metadata
│       │   ├── cache.py          # Two-tier caching (LRU + disk)
│       │   ├── exceptions.py     # FMP-specific exceptions
│       │   └── compat.py         # Backward-compatible wrappers
│       └── data_loader.py        # Existing loader (migrates to use fmp/)
└── utils/
    └── config.py                 # Add FMP_* configuration constants
```

**Import paths after migration:**
```python
# New preferred API
from loaders.financial_data.fmp import FMPClient

# Backward compatible (via compat.py)
from loaders.financial_data.fmp.compat import fetch_monthly_close
```

---

## Component Details

### 1. Endpoint Registry (`fmp/registry.py`)

Declarative endpoint definitions with full metadata for discoverability:

```python
from dataclasses import dataclass, field
from typing import List, Optional, Any
from enum import Enum

class ParamType(Enum):
    STRING = "string"
    DATE = "date"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"

@dataclass
class EndpointParam:
    """Parameter definition for an FMP endpoint."""
    name: str
    param_type: ParamType
    required: bool = False
    description: str = ""
    default: Any = None
    enum_values: Optional[List[str]] = None
    api_name: Optional[str] = None  # FMP param name if different

@dataclass
class FMPEndpoint:
    """Declarative definition of an FMP API endpoint."""
    # Identity
    name: str                           # Internal name: "income_statement"
    path: str                           # API path: "/income-statement" (without base)
    api_version: str = "stable"         # "stable" or "v3" - determines base URL

    # Documentation
    description: str                    # Human-readable description
    fmp_docs_url: str                   # Link to FMP documentation
    category: str                       # Category: "fundamentals", "prices", etc.

    # Parameters
    params: List[EndpointParam] = field(default_factory=list)

    # Caching
    cache_enabled: bool = True
    cache_dir: str = "cache_fmp"
    cache_ttl_hours: Optional[int] = None  # None = disk cache (no TTL)
    cache_key_strategy: str = "hash"    # "hash" (MD5) or "monthly" (YYYYMM token)

    # Response handling
    response_type: str = "list"         # "list", "dict", "single"
    response_path: Optional[str] = None # Path to extract data from response (see below)
    date_column: Optional[str] = "date"
    response_transform: Optional[Callable] = None  # Custom transform function

# response_path formats:
#   - Single key: "historical" → response["historical"]
#   - Dot-path:   "data.items" → response["data"]["items"]
#   - None:       Use response as-is
#
# For complex extraction beyond dot-paths, use response_transform callable instead.

# Global registry
ENDPOINT_REGISTRY: Dict[str, FMPEndpoint] = {}

def register_endpoint(endpoint: FMPEndpoint) -> FMPEndpoint:
    """Register an endpoint in the global registry."""
    ENDPOINT_REGISTRY[endpoint.name] = endpoint
    return endpoint
```

**Example endpoint registrations:**

```python
# Simple endpoint (stable API, flat response)
register_endpoint(FMPEndpoint(
    name="income_statement",
    path="/income-statement",
    api_version="stable",              # Uses stable base URL
    description="Income statement data (revenue, net income, EPS, etc.)",
    fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#income-statement",
    category="fundamentals",
    params=[
        EndpointParam("symbol", ParamType.STRING, required=True),
        EndpointParam("period", ParamType.ENUM, default="annual",
                     enum_values=["annual", "quarter"]),
        EndpointParam("limit", ParamType.INTEGER, default=10),
    ],
    cache_dir="cache_fundamentals",
))

# Endpoint with nested response (historical prices wrap data in "historical" key)
register_endpoint(FMPEndpoint(
    name="historical_price_eod",
    path="/historical-price-eod/full",
    api_version="stable",
    description="End-of-day historical prices",
    fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#historical-price-eod",
    category="prices",
    params=[
        EndpointParam("symbol", ParamType.STRING, required=True),
        EndpointParam("from_date", ParamType.DATE, api_name="from"),
        EndpointParam("to_date", ParamType.DATE, api_name="to"),
    ],
    cache_dir="cache_prices",
    cache_key_strategy="monthly",      # Use YYYYMM tokens for natural monthly refresh
    response_path="historical",        # Extract data from {"historical": [...]}
))

# V3 API endpoint (different base URL)
register_endpoint(FMPEndpoint(
    name="search",
    path="/search",
    api_version="v3",                  # Uses /api/v3 base URL
    description="Search for companies by name or symbol",
    fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#search",
    category="search",
    params=[
        EndpointParam("query", ParamType.STRING, required=True),
        EndpointParam("limit", ParamType.INTEGER, default=10),
    ],
    cache_enabled=False,               # Don't cache search results
))
```

---

### 2. Client Interface (`fmp/client.py`)

Single entry point for all FMP data access:

```python
class FMPClient:
    """
    Unified client for all FMP API interactions.

    Features:
    - Single entry point for all FMP endpoints
    - Automatic caching (disk + LRU)
    - Rate limit handling with exponential backoff
    - Comprehensive error handling and logging
    - Parameter validation
    - Discoverability via list_endpoints() and describe()
    """

    STABLE_BASE_URL = "https://financialmodelingprep.com/stable"
    V3_BASE_URL = "https://financialmodelingprep.com/api/v3"

    def __init__(self, api_key: Optional[str] = None, cache_enabled: bool = True):
        """
        Initialize FMP client.

        Environment loading: Client calls load_dotenv() internally to ensure
        FMP_API_KEY is available even if app hasn't initialized it yet.
        This matches the pattern in existing data_loader.py.

        API Key Behavior: "Lazy error on fetch" (not fail-fast)
        - Missing key at init: logs warning, allows instantiation
        - Missing key at fetch: raises FMPError
        - Rationale: Matches current data_loader.py behavior where missing
          key doesn't fail until an actual API call is made. This allows
          the client to be instantiated for discovery (list_endpoints,
          describe) without requiring credentials.
        """
        from dotenv import load_dotenv
        load_dotenv()  # Ensure .env is loaded

        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            from utils.logging import portfolio_logger
            portfolio_logger.warning("FMP_API_KEY not found. API calls will fail until key is provided.")
        self.cache_enabled = cache_enabled
        self._cache = FMPCache() if cache_enabled else None

    # === Primary Interface ===

    def fetch(self, endpoint_name: str, *, use_cache: bool = True,
              as_dataframe: bool = True, **params) -> pd.DataFrame:
        """
        Fetch data from an FMP endpoint.

        Args:
            endpoint_name: Name of endpoint (e.g., "income_statement")
            use_cache: Override endpoint cache setting
            as_dataframe: Convert response to DataFrame
            **params: Endpoint parameters (symbol, from_date, etc.)

        Returns:
            DataFrame or raw JSON response
        """
        ...

    # === Convenience Methods ===

    def get_monthly_prices(self, symbol: str, start_date: str = None,
                          end_date: str = None, adjusted: bool = True) -> pd.Series:
        """Get month-end prices with optional dividend adjustment."""
        ...

    def get_treasury_rates(self, maturity: str = "year10",
                          start_date: str = None, end_date: str = None) -> pd.Series:
        """Get Treasury rates for a specific maturity."""
        ...

    # === Discoverability ===

    def list_endpoints(self, category: Optional[str] = None) -> List[Dict]:
        """List available endpoints with descriptions."""
        ...

    def list_categories(self) -> List[str]:
        """List all endpoint categories."""
        ...

    def describe(self, endpoint_name: str) -> Dict:
        """Get detailed documentation for an endpoint."""
        ...

    def generate_documentation(self) -> str:
        """Generate markdown documentation for all endpoints."""
        ...
```

**Usage examples:**

```python
from fmp import FMPClient

fmp = FMPClient()

# === Fetching Data ===

# Historical prices
prices = fmp.fetch("historical_price_adjusted",
                   symbol="AAPL",
                   from_date="2020-01-01",
                   to_date="2024-01-01")

# Income statement
income = fmp.fetch("income_statement",
                   symbol="AAPL",
                   period="quarter",
                   limit=8)

# Analyst estimates
estimates = fmp.fetch("analyst_estimates", symbol="NVDA")

# === Convenience Methods ===

monthly_prices = fmp.get_monthly_prices("AAPL", adjusted=True)
treasury_10y = fmp.get_treasury_rates("year10")

# === Discoverability ===

# List all endpoints
fmp.list_endpoints()
# [{'name': 'income_statement', 'description': '...', 'category': 'fundamentals'}, ...]

# Filter by category
fmp.list_endpoints(category="analyst")

# Get full documentation for an endpoint
fmp.describe("income_statement")
# {
#     "name": "income_statement",
#     "description": "Income statement data...",
#     "docs_url": "https://...",
#     "parameters": [
#         {"name": "symbol", "type": "string", "required": True, ...},
#         {"name": "period", "type": "enum", "enum_values": ["annual", "quarter"], ...},
#     ],
#     ...
# }

# Generate markdown docs
docs = fmp.generate_documentation()
```

---

### 3. Caching Layer (`fmp/cache.py`)

Two-tier caching following existing patterns from `data_loader.py`:

```python
class FMPCache:
    """
    Two-tier caching for FMP data.

    Tier 1: In-memory LRU cache for hot data
    Tier 2: Disk cache (Parquet with Zstandard) for persistence
    """

    def generate_key(self, endpoint: FMPEndpoint, params: Dict) -> str:
        """
        Generate cache key based on endpoint's cache_key_strategy.

        Strategies:
        - "hash": MD5 hash of [endpoint, params] (default)
        - "monthly": Include YYYYMM token for natural monthly refresh
        """
        if endpoint.cache_key_strategy == "monthly":
            # Match existing data_loader.py pattern
            month_token = datetime.now().strftime("%Y%m")
            parts = [endpoint.name, month_token, *sorted(params.items())]
        else:
            parts = [endpoint.name, *sorted(params.items())]
        return hashlib.md5(str(parts).encode()).hexdigest()[:12]

    def get(self, key: str, endpoint: FMPEndpoint) -> Optional[pd.DataFrame]:
        """Get cached data, checking LRU first then disk."""
        ...

    def set(self, key: str, data: pd.DataFrame, endpoint: FMPEndpoint) -> None:
        """Cache data in appropriate tier(s)."""
        ...
```

**Cache key strategies (matching existing patterns):**

| Strategy | Use Case | Behavior |
|----------|----------|----------|
| `hash` | Most endpoints | MD5 hash of params, stable across time |
| `monthly` | Prices, dividends | Includes YYYYMM token, auto-refreshes monthly |

**Cache behavior per endpoint type:**
- **Prices/Treasury**: Disk cache (Parquet), `monthly` key strategy, no TTL
- **Analyst Data**: TTL cache (12-24 hours), `hash` key strategy
- **Search**: No caching — results should be fresh

**LRU sizes:** Reuse existing `DATA_LOADER_LRU_SIZE`, `TREASURY_RATE_LRU_SIZE`, `DIVIDEND_LRU_SIZE` from `utils/config.py` rather than defining new constants.

---

### 4. Backward Compatibility (`fmp/compat.py`)

**CRITICAL:** Wrappers must replicate **exact behavior** of existing functions, not just signatures. This includes:
- Fallback chains (e.g., try adjusted → fall back to unadjusted)
- Month-end resampling logic
- Dividend frequency detection and TTM calculation
- Series naming conventions (e.g., `{ticker}_total_return` vs `{ticker}_price_only`)

```python
def fetch_monthly_close(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict] = None,
) -> pd.Series:
    """
    Backward-compatible wrapper for fetch_monthly_close.

    MUST replicate:
    - Ticker resolution via select_fmp_symbol()
    - Month-end resampling: resample("ME")["close"].last()
    - Series name: ticker symbol
    - Empty series handling
    """
    from utils.ticker_resolver import select_fmp_symbol

    symbol = select_fmp_symbol(ticker, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map)
    df = get_client().fetch("historical_price_eod", symbol=symbol,
                            from_date=start_date, to_date=end_date)
    if df.empty:
        return pd.Series(dtype=float, name=ticker)

    # Match existing resampling behavior
    monthly = df.resample("ME")["close"].last()
    monthly.name = ticker
    return monthly


def fetch_monthly_total_return_price(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    fmp_ticker: Optional[str] = None,
    fmp_ticker_map: Optional[dict] = None,
) -> pd.Series:
    """
    Backward-compatible wrapper for fetch_monthly_total_return_price.

    MUST replicate:
    - Try dividend-adjusted endpoint first
    - Fall back to unadjusted if adjusted fails
    - Series name: "{ticker}_total_return" or "{ticker}_price_only"
    - Month-end resampling
    """
    from utils.ticker_resolver import select_fmp_symbol

    symbol = select_fmp_symbol(ticker, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map)
    client = get_client()

    # Try adjusted first
    try:
        df = client.fetch("historical_price_adjusted", symbol=symbol,
                         from_date=start_date, to_date=end_date)
        if not df.empty and "adjClose" in df.columns:
            monthly = df.resample("ME")["adjClose"].last()
            monthly.name = f"{ticker}_total_return"
            return monthly
    except Exception:
        pass

    # Fallback to unadjusted
    df = client.fetch("historical_price_eod", symbol=symbol,
                     from_date=start_date, to_date=end_date)
    if df.empty:
        return pd.Series(dtype=float, name=f"{ticker}_price_only")

    monthly = df.resample("ME")["close"].last()
    monthly.name = f"{ticker}_price_only"
    return monthly


def fetch_dividend_history(ticker: str, ...) -> pd.DataFrame:
    """
    Backward-compatible wrapper for fetch_dividend_history.

    MUST replicate:
    - Frequency-based TTM calculation (not date-based)
    - Quarterly → last 4 payments
    - Monthly → last 12 payments
    - Annual → last 1 payment
    - Return columns: adjDividend, yield, frequency
    """
    # Complex logic preserved from data_loader.py
    ...
```

**Testing requirement:** Each compat function must be tested against the original function with identical inputs to verify output matches.

**Migration path:**
```python
# Before:
from data_loader import fetch_monthly_close

# After (drop-in replacement):
from loaders.financial_data.fmp.compat import fetch_monthly_close

# Or use new API directly:
from loaders.financial_data.fmp import FMPClient
fmp = FMPClient()
prices = fmp.get_monthly_prices("AAPL", adjusted=False)
```

---

### 5. Exceptions (`fmp/exceptions.py`)

```python
class FMPError(RiskModuleException):
    """Base exception for FMP-related errors."""
    pass

class FMPAPIError(FMPError):
    """Raised when FMP API request fails."""
    def __init__(self, message: str, status_code: int = None):
        ...

class FMPRateLimitError(FMPAPIError):
    """Raised when rate limited by FMP."""
    pass

class FMPEndpointNotFoundError(FMPError):
    """Raised when endpoint not found in registry."""
    pass

class FMPValidationError(FMPError):
    """Raised when parameter validation fails."""
    pass
```

---

## Endpoints to Register

### Initial (Migrate from existing code)

| Category | Endpoint | Source |
|----------|----------|--------|
| prices | `historical_price_eod` | data_loader.py |
| prices | `historical_price_adjusted` | data_loader.py |
| treasury | `treasury_rates` | data_loader.py |
| dividends | `dividends` | data_loader.py |
| search | `search` | ticker_resolver.py |
| search | `profile` | ticker_resolver.py |

### New (High-value additions)

| Category | Endpoint | Use Case |
|----------|----------|----------|
| fundamentals | `income_statement` | Financial analysis |
| fundamentals | `balance_sheet` | Financial analysis |
| fundamentals | `cash_flow` | Financial analysis |
| fundamentals | `key_metrics` | Ratio analysis |
| analyst | `analyst_estimates` | Estimate revisions |
| analyst | `price_target` | Analyst consensus |

### Future Expansion

| Category | Endpoints |
|----------|-----------|
| sec | `sec_filings`, `insider_trading`, `institutional_holders` |
| earnings | `earnings_calendar`, `earnings_transcript` |
| economic | `economic_calendar`, `gdp`, `unemployment` |
| etf | `etf_holdings`, `etf_sector_weightings` |

---

## Adding New Endpoints

Adding a new endpoint is a single function call:

```python
# In fmp/registry.py

register_endpoint(FMPEndpoint(
    name="analyst_recommendations",
    path="/analyst-recommendations",        # Path without base URL prefix
    api_version="stable",                   # Determines base URL
    description="Analyst buy/sell/hold recommendations with counts.",
    fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#analyst-recommendation",
    category="analyst",
    params=[
        EndpointParam("symbol", ParamType.STRING, required=True,
                     description="Ticker symbol"),
    ],
    cache_dir="cache_analyst",
    cache_ttl_hours=24,
))
```

Immediately usable:
```python
fmp.fetch("analyst_recommendations", symbol="AAPL")
```

---

## Logging

**Decision:** Use existing custom logging from `utils/logging.py` (not standard Python `logging`).

**Rationale:**
- Consistent with rest of codebase
- Leverages existing health tracking, rate limit logging, and alerting
- FMP layer needs API monitoring which custom logging already provides

**Functions to use:**

| Function | Use Case |
|----------|----------|
| `portfolio_logger` | General logging (info, warning, debug) |
| `log_service_health()` | Track FMP API health (healthy/degraded/down) |
| `log_rate_limit_hit()` | Log 429 rate limit events |
| `log_critical_alert()` | High-priority errors requiring attention |
| `@log_error_handling()` | Decorator for exception capture |
| `@log_performance()` | Decorator for timing slow operations |

---

## Configuration (`utils/config.py`)

**Reuse existing constants where possible** to avoid drift:

```python
# === FMP API Settings ===
# These are NEW (no existing equivalent)
FMP_REQUEST_TIMEOUT = int(os.getenv("FMP_REQUEST_TIMEOUT", "30"))
FMP_MAX_RETRIES = int(os.getenv("FMP_MAX_RETRIES", "3"))

# REUSE existing constants (don't duplicate)
# - DATA_LOADER_LRU_SIZE (already exists, use for FMP LRU cache)
# - TREASURY_RATE_LRU_SIZE (already exists)
# - DIVIDEND_LRU_SIZE (already exists)

# Rate limiting: If a similar constant exists, use it; otherwise add:
FMP_RATE_LIMIT_DELAY = float(os.getenv("FMP_RATE_LIMIT_DELAY", "0.1"))
```

**Important:** Before adding new constants, check `utils/config.py` for existing equivalents to maintain single source of truth.

---

## Future: MCP Server

The registry-based design naturally maps to MCP tool definitions:

```python
def _param_to_json_schema(param: EndpointParam) -> Dict:
    """Convert EndpointParam to JSON Schema property."""
    # Map ParamType to valid JSON Schema types
    type_map = {
        ParamType.STRING: {"type": "string"},
        ParamType.DATE: {"type": "string", "format": "date"},  # ISO 8601 date
        ParamType.INTEGER: {"type": "integer"},
        ParamType.FLOAT: {"type": "number"},
        ParamType.BOOLEAN: {"type": "boolean"},
        ParamType.ENUM: {"type": "string", "enum": param.enum_values},
    }
    schema = type_map.get(param.param_type, {"type": "string"})
    schema["description"] = param.description
    return schema


def generate_mcp_tools() -> List[Dict]:
    """Generate MCP tool definitions from FMP registry."""
    tools = []
    for endpoint in ENDPOINT_REGISTRY.values():
        tools.append({
            "name": f"fmp_{endpoint.name}",
            "description": endpoint.description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    param.name: _param_to_json_schema(param)
                    for param in endpoint.params
                },
                "required": [p.name for p in endpoint.params if p.required],
            },
        })
    return tools
```

---

## Implementation Phases

### Phase 1: Core Module
1. Create `loaders/financial_data/fmp/` package structure
2. Implement `exceptions.py`
3. Add config constants to `utils/config.py`
4. Implement `registry.py` with endpoint dataclasses
5. Implement `cache.py`
6. Implement `client.py`

### Phase 2: Register Endpoints
7. Register existing endpoints (prices, treasury, dividends, search)
8. Implement `compat.py` for backward compatibility

### Phase 3: Expand
9. Register new endpoints (fundamentals, analyst)
10. Add tests

### Phase 4: Documentation
11. Auto-generate endpoint documentation
12. Add usage examples

### Relationship to Modular Architecture Migration

This FMP layer can be implemented **before or during** the broader modular architecture refactor:

- **Before:** Create `loaders/financial_data/fmp/` now. When the full migration happens, it's already in place.
- **During:** Implement as part of the Loaders layer migration.

The FMP layer has no dependencies on other parts of the modular refactor — it only depends on `utils/config.py` and existing caching patterns.

### Package Creation Requirement

**The `loaders/` package does not exist yet.** Implementation must either:

**Option A: Create the full path now (recommended)**
```bash
mkdir -p loaders/financial_data/fmp
touch loaders/__init__.py
touch loaders/financial_data/__init__.py
touch loaders/financial_data/fmp/__init__.py
```
This creates the structure upfront, aligned with the modular architecture plan.

**Option B: Interim path at root level**
```
risk_module/
├── fmp/                      # Temporary location at root
│   ├── __init__.py
│   ├── client.py
│   └── ...
```
Use `fmp/` at root for now, move to `loaders/financial_data/fmp/` during the modular refactor. This avoids creating partial `loaders/` structure.

**Recommendation:** Option A is cleaner. Creating `loaders/` now doesn't conflict with anything and establishes the target structure.

---

## Files Summary

| File | Purpose | ~Lines |
|------|---------|--------|
| `loaders/financial_data/__init__.py` | Re-exports from fmp/ | 10 |
| `loaders/financial_data/fmp/__init__.py` | Public API exports | 20 |
| `loaders/financial_data/fmp/client.py` | FMPClient class | 250 |
| `loaders/financial_data/fmp/registry.py` | Endpoint definitions | 300 |
| `loaders/financial_data/fmp/cache.py` | Caching layer | 100 |
| `loaders/financial_data/fmp/exceptions.py` | Exception classes | 40 |
| `loaders/financial_data/fmp/compat.py` | Backward-compatible wrappers | 100 |
| `loaders/financial_data/fmp/README.md` | Claude-friendly entry point | 80 |
| `utils/config.py` | Add FMP constants | +10 |

---

## Claude-Friendly README

The following README should be created at `loaders/financial_data/fmp/README.md` to serve as an entry point for Claude when exploring the codebase:

```markdown
# FMP Data Layer

This module provides unified access to Financial Modeling Prep (FMP) API data.

## Quick Start

```python
from loaders.financial_data.fmp import FMPClient

fmp = FMPClient()

# Fetch data
prices = fmp.fetch("historical_price_adjusted", symbol="AAPL")
income = fmp.fetch("income_statement", symbol="AAPL", period="quarter")
```

## Discovering Available Data

### Option 1: Read the Registry
See `registry.py` for all available endpoints with:
- Endpoint name and description
- Required and optional parameters
- Link to FMP documentation
- Caching behavior

### Option 2: Runtime Discovery
```python
fmp = FMPClient()

# List all endpoints
fmp.list_endpoints()

# List by category
fmp.list_endpoints(category="fundamentals")
fmp.list_endpoints(category="analyst")

# Get full details for an endpoint
fmp.describe("income_statement")
```

### Option 3: Generate Documentation
```python
docs = fmp.generate_documentation()
print(docs)  # Full markdown documentation
```

## Available Categories

| Category | Examples |
|----------|----------|
| `prices` | Historical prices (adjusted and unadjusted) |
| `treasury` | Treasury rates (2Y, 5Y, 10Y, 30Y) |
| `dividends` | Dividend history |
| `fundamentals` | Income statement, balance sheet, cash flow, key metrics |
| `analyst` | Analyst estimates, price targets |
| `search` | Company search, profiles |

## Common Patterns

### Get monthly prices for analysis
```python
prices = fmp.get_monthly_prices("AAPL", start_date="2020-01-01", adjusted=True)
```

### Get financial statements
```python
# Quarterly income statements, last 8 quarters
income = fmp.fetch("income_statement", symbol="AAPL", period="quarter", limit=8)

# Annual balance sheet
balance = fmp.fetch("balance_sheet", symbol="AAPL", period="annual")
```

### Get analyst data
```python
estimates = fmp.fetch("analyst_estimates", symbol="NVDA")
targets = fmp.fetch("price_target", symbol="NVDA")
```

## Adding New Endpoints

To add a new FMP endpoint, add a `register_endpoint()` call in `registry.py`:

```python
register_endpoint(FMPEndpoint(
    name="new_endpoint",
    path="/new-endpoint",           # Path without base URL prefix
    api_version="stable",           # "stable" or "v3"
    description="Description of what this endpoint returns",
    fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#...",
    category="category_name",
    params=[
        EndpointParam("symbol", ParamType.STRING, required=True),
    ],
))
```

The endpoint is immediately available via `fmp.fetch("new_endpoint", symbol="AAPL")`.

## For More Details

- **Full design:** `docs/fmp_layer_design.md`
- **FMP API docs:** https://site.financialmodelingprep.com/developer/docs
```

---

## References

- [FMP API Documentation](https://site.financialmodelingprep.com/developer/docs)
- [Modular Architecture Plan](./planning/MODULAR_ARCHITECTURE_REFACTOR_PLAN.md)
- Existing patterns: `data_loader.py`, `utils/ticker_resolver.py`
- Caching: `cache_read()`, `cache_write()` functions in `data_loader.py`
