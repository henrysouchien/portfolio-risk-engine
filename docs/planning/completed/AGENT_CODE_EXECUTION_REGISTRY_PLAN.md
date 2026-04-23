# Agent Code Execution Registry — Implementation Plan

**Status**: Draft v6
**Created**: 2026-03-15
**Codex reviews**: v1 FAIL (7), v2 FAIL (7), v3 FAIL (5), v4 FAIL (2), v5 FAIL (1 — FMP stdout). All addressed in v6.

---

## Context

The analyst agent (Claude via gateway) currently only interacts via MCP tools. MCP can't handle ad-hoc analysis — every new question requires a new tool. Code execution lets the agent write Python that calls back into the API, then computes whatever it needs.

### Current State

- **73 MCP tools** in `mcp_tools/*.py`, registered in `mcp_server.py`
- **Code execution** happens remotely at the Claude gateway
- **Consumer-level integration**: env vars and system prompt configured at consumer (frontend/Excel addin), not the gateway

---

## Architecture

```
Tier 1: mcp_tools/*.py      ← unwrapped from @handle_mcp_errors for HTTP path
Tier 2: core building blocks ← new functions with @handle_http_errors
              ↓
   Agent Function Registry   ← explicit allowlist, read-only default
              ↓
   POST /api/agent/call      ← RPC endpoint (bearer-only auth, param sanitization)
              ↓
   risk_client package        ← thin HTTP client (pip-installable)
```

### Key Design Decisions

**Unwrapped functions**: The registry stores the **unwrapped** inner function (via `fn.__wrapped__`), NOT the `@handle_mcp_errors`-decorated version. This avoids the thread-unsafe `sys.stdout` swap that `handle_mcp_errors` does for MCP stdio protection. The RPC endpoint wraps calls with `handle_http_errors` instead — same exception handling, no stdout mutation.

**Explicit allowlist**: NOT all 73 MCP tools. Curated subset excluding file-path tools, normalizer builder, admin config, and functions that resolve user from process globals.

**Param sanitization**: Blocked params (`backfill_path`, `output`) are stripped/forced before dispatch. `user_email` always injected server-side.

**Bearer-only auth**: No cookie fallback. Fail closed when key is empty.

**Read-only default**: Mutations blocked unless `AGENT_API_ALLOW_WRITES=true`.

---

## Codex Findings Tracker

| # | v1 Finding | v2 Finding | v3 Resolution |
|---|-----------|-----------|---------------|
| 1 | 15+ tools lack user_email | "Stateless" bucket misclassified (only 4→5 truly stateless) | Corrected: 28 with user_email + 5 truly stateless = 33 read-only. `analyze_stock` moved to stateless. `get_action_history`/`get_target_allocation` excluded. `get_portfolio_news`/`get_portfolio_events_calendar` deferred (FMP helper stdout swap). |
| 2 | Empty key passes compare_digest | Cookie fallback bypasses fail-closed | Bearer-only. No cookie fallback. Empty key → 503. |
| 3 | @handle_mcp_errors swaps stdout | Still calling decorated functions triggers swap | Registry stores `fn.__wrapped__` (unwrapped). RPC uses `handle_http_errors`. |
| 4 | File-path tools won't work over HTTP | `backfill_path` + `output="file"` still open | `BLOCKED_PARAMS`: strips `backfill_path`, forces `output="inline"`, forces `debug_inference=False`. `export_holdings` excluded. |
| 5 | Name drift between registry/client/MCP | Client missing 9 Phase 1 functions, has 10 Phase 1b | Client convenience methods match Phase 1 allowlist exactly. Phase 1b methods deferred to Phase 1b. |
| 6 | Hardening should be Phase 1 | Validation only rejects unknown params | Required param enforcement, blocked param stripping. Error dicts without `error_type` get post-processed. |
| 7 | `_is_infra_error` too narrow, name shadows | `@require_db` returns plain dicts without error_type | Post-process: dicts with `status: "error"` but no `error_type` get classified. Fully-qualified DB exception imports. |

---

## Phase 1 — Read-Only Registry + Infrastructure

### Step 1: HTTP Error Decorator — `mcp_tools/common.py`

```python
def handle_http_errors(fn: Callable) -> Callable:
    """Error handler for HTTP-served agent functions.

    Same exception handling as handle_mcp_errors but does NOT touch
    sys.stdout — safe for concurrent HTTP requests.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            portfolio_logger.error(f"{fn.__name__} failed: {e}")
            # DB error detection
            try:
                from app_platform.db import exceptions as db_exc
                if isinstance(e, (db_exc.PoolExhaustionError, db_exc.ConnectionError)):
                    from database import mark_db_unavailable
                    mark_db_unavailable()
            except Exception:
                pass
            # Auth error classification
            auth_msg = _classify_auth_error(e)
            if auth_msg:
                return {"status": "error", "error": auth_msg, "auth_required": True, "error_type": "auth"}
            error_type = _classify_error_type(e)
            return {"status": "error", "error": str(e), "error_type": error_type}
    return wrapper

def _classify_error_type(e: Exception) -> str:
    """Classify exception as infrastructure vs business error."""
    try:
        from app_platform.db import exceptions as db_exc
        if isinstance(e, (db_exc.PoolExhaustionError, db_exc.ConnectionError)):
            return "infrastructure"
    except Exception:
        pass
    # Built-in infrastructure errors (fully qualified, no name shadows)
    if isinstance(e, (OSError, TimeoutError, ConnectionError)):
        return "infrastructure"
    # requests/urllib3 network errors
    try:
        import requests.exceptions
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return "infrastructure"
    except ImportError:
        pass
    return "business"
```

### Step 2: Function Registry — `services/agent_registry.py`

```python
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

@dataclass(frozen=True)
class AgentFunction:
    callable: Callable      # the UNWRAPPED function (no @handle_mcp_errors)
    tier: Literal["tool", "building_block"]
    read_only: bool
    category: str
    has_user_email: bool

# Params that are stripped/forced for security
BLOCKED_PARAMS = {
    "backfill_path": None,       # stripped (arbitrary file read)
    "output": "inline",          # forced to "inline" (no file writes)
    "debug_inference": False,    # forced off (writes diagnostics JSON even without output="file")
}

AGENT_FUNCTIONS: dict[str, AgentFunction] = {}

def get_registry() -> dict[str, AgentFunction]:
    if not AGENT_FUNCTIONS:
        _build_registry()
    return AGENT_FUNCTIONS

def _unwrap(fn: Callable) -> Callable:
    """Get the unwrapped function, bypassing @handle_mcp_errors."""
    return getattr(fn, "__wrapped__", fn)

def _register(name, fn, *, tier="tool", read_only=True, category="general"):
    unwrapped = _unwrap(fn)
    has_user_email = "user_email" in inspect.signature(unwrapped).parameters
    AGENT_FUNCTIONS[name] = AgentFunction(
        callable=unwrapped,
        tier=tier,
        read_only=read_only,
        category=category,
        has_user_email=has_user_email,
    )

def _build_registry():
    """Build registry — lazy imports to avoid startup cost."""

    # --- Tier 1: Read-only tools with user_email (28) ---

    from mcp_tools.positions import get_positions
    _register("get_positions", get_positions, category="positions")
    # NOTE: export_holdings excluded — defaults to output="file"

    from mcp_tools.risk import (
        get_risk_score, get_risk_analysis, get_leverage_capacity, get_risk_profile,
    )
    _register("get_risk_score", get_risk_score, category="risk")
    _register("get_risk_analysis", get_risk_analysis, category="risk")
    _register("get_leverage_capacity", get_leverage_capacity, category="risk")
    _register("get_risk_profile", get_risk_profile, category="risk")

    from mcp_tools.performance import get_performance
    _register("get_performance", get_performance, category="performance")

    from mcp_tools.optimization import run_optimization, get_efficient_frontier
    _register("run_optimization", run_optimization, category="optimization")
    _register("get_efficient_frontier", get_efficient_frontier, category="optimization")

    from mcp_tools.whatif import run_whatif
    _register("run_whatif", run_whatif, category="scenarios")

    from mcp_tools.backtest import run_backtest
    _register("run_backtest", run_backtest, category="scenarios")

    # NOTE: analyze_stock has no user_email — registered below with stateless tools

    from mcp_tools.trading_analysis import get_trading_analysis
    _register("get_trading_analysis", get_trading_analysis, category="analysis")

    from mcp_tools.income import get_income_projection
    _register("get_income_projection", get_income_projection, category="income")

    from mcp_tools.tax_harvest import suggest_tax_loss_harvest
    _register("suggest_tax_loss_harvest", suggest_tax_loss_harvest, category="income")

    from mcp_tools.transactions import (
        list_transactions, list_ingestion_batches, inspect_transactions,
        list_flow_events, list_income_events, transaction_coverage,
    )
    _register("list_transactions", list_transactions, category="transactions")
    _register("list_ingestion_batches", list_ingestion_batches, category="transactions")
    _register("inspect_transactions", inspect_transactions, category="transactions")
    _register("list_flow_events", list_flow_events, category="transactions")
    _register("list_income_events", list_income_events, category="transactions")
    _register("transaction_coverage", transaction_coverage, category="transactions")

    from mcp_tools.hedge_monitor import monitor_hedge_positions
    _register("monitor_hedge_positions", monitor_hedge_positions, category="risk")

    # NOTE: get_portfolio_news and get_portfolio_events_calendar excluded from Phase 1.
    # Their inner FMP helpers (fmp/tools/news_events.py) do sys.stdout = sys.stderr,
    # which is thread-unsafe on the HTTP path. Add back after FMP helpers are fixed.

    from mcp_tools.baskets import list_baskets, get_basket
    _register("list_baskets", list_baskets, category="baskets")
    _register("get_basket", get_basket, category="baskets")

    from mcp_tools.compare import compare_scenarios
    _register("compare_scenarios", compare_scenarios, category="scenarios")

    from mcp_tools.factor_intelligence import get_factor_analysis, get_factor_recommendations
    _register("get_factor_analysis", get_factor_analysis, category="analysis")
    _register("get_factor_recommendations", get_factor_recommendations, category="analysis")

    from mcp_tools.rebalance import preview_rebalance_trades
    _register("preview_rebalance_trades", preview_rebalance_trades, category="analysis")

    from mcp_tools.signals import check_exit_signals
    _register("check_exit_signals", check_exit_signals, category="analysis")

    from mcp_tools.trading import get_orders
    _register("get_orders", get_orders, category="trading")

    # --- Tier 1: Truly stateless tools (5) — no user_email param ---

    from mcp_tools.stock import analyze_stock
    _register("analyze_stock", analyze_stock, category="analysis")

    from mcp_tools.quote import get_quote
    _register("get_quote", get_quote, category="market")

    from mcp_tools.futures_curve import get_futures_curve
    _register("get_futures_curve", get_futures_curve, category="market")

    from mcp_tools.chain_analysis import analyze_option_chain
    _register("analyze_option_chain", analyze_option_chain, category="options")

    from mcp_tools.options import analyze_option_strategy
    _register("analyze_option_strategy", analyze_option_strategy, category="options")

    # --- Tier 2: Building blocks (added in Phase 1b) ---
```

**Total Phase 1**: 33 functions (28 with user_email + 5 stateless)

**Explicitly excluded**:
```
# File-path tools (remote sandbox has no local filesystem)
import_portfolio, import_transaction_file

# Normalizer builder (writes arbitrary Python to disk)
normalizer_sample_csv, normalizer_stage, normalizer_test, normalizer_activate, normalizer_list

# Admin/global config (not user-scoped)
manage_instrument_config, manage_ticker_config

# Implicit user resolution (resolve from process globals, not user_email param)
get_target_allocation, get_action_history, record_workflow_action, update_action_status

# Defaults to file output
export_holdings

# FMP helper stdout swap (thread-unsafe) — add back after FMP helpers fixed
get_portfolio_news, get_portfolio_events_calendar
```

### Step 3: Bearer-Only Auth — `routes/agent_api.py`

No cookie fallback. Fail closed.

```python
import os
import secrets
from fastapi import Depends, HTTPException, Request

AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")

def get_agent_user(request: Request) -> dict:
    """Resolve user from bearer token. Fail closed — no fallbacks."""
    if not AGENT_API_KEY:
        raise HTTPException(503, "Agent API not configured (AGENT_API_KEY not set)")

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")

    token = auth[7:]
    if not token or not secrets.compare_digest(token, AGENT_API_KEY):
        raise HTTPException(401, "Invalid API key")

    return _resolve_agent_user()

def _resolve_agent_user() -> dict:
    """Resolve user from RISK_MODULE_USER_EMAIL env var."""
    from utils.user_context import resolve_user_email
    email, _context = resolve_user_email()  # returns (email, debug_context) tuple
    if not email:
        raise HTTPException(500, "RISK_MODULE_USER_EMAIL not configured")
    return {"email": email, "source": "agent_api_key"}
```

### Step 4: RPC Endpoint — `routes/agent_api.py`

```python
import inspect
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from services.agent_registry import get_registry, BLOCKED_PARAMS
from mcp_tools.common import handle_http_errors, _classify_error_type

router = APIRouter()
ALLOW_WRITES = os.environ.get("AGENT_API_ALLOW_WRITES", "").lower() == "true"

@router.post("/call")
@limiter.limit("60/minute")
async def agent_call(
    request: Request,
    body: dict = Body(...),
    user: dict = Depends(get_agent_user),
):
    function_name = body.get("function")
    if not function_name or not isinstance(function_name, str):
        raise HTTPException(400, "Missing or invalid 'function' field")

    params = body.get("params", {})
    if not isinstance(params, dict):
        raise HTTPException(400, "'params' must be a dict")

    registry = get_registry()
    entry = registry.get(function_name)
    if not entry:
        raise HTTPException(404, f"Unknown function: {function_name}")

    # Read-only gate
    if not entry.read_only and not ALLOW_WRITES:
        raise HTTPException(403, f"'{function_name}' is a mutation. Set AGENT_API_ALLOW_WRITES=true to enable.")

    # Param sanitization
    params = _sanitize_params(params, entry)

    # User injection
    if entry.has_user_email:
        params["user_email"] = user["email"]

    # Execute via handle_http_errors (no stdout swap)
    result = await run_in_threadpool(_http_dispatch, entry.callable, params)

    # Post-process: ensure error_type on all error responses.
    # Inner functions may return {"status": "error", ...} without error_type
    # (from @require_db, internal auth catches, etc.) — classify after the fact.
    if isinstance(result, dict) and result.get("status") == "error" and "error_type" not in result:
        if result.get("auth_required"):
            result["error_type"] = "auth"
        else:
            error_msg = result.get("error", "").lower()
            if "database" in error_msg or "db" in error_msg or "postgresql" in error_msg:
                result["error_type"] = "infrastructure"
            else:
                result["error_type"] = "business"

    ok = isinstance(result, dict) and result.get("status") != "error"
    return {
        "function": function_name,
        "ok": ok,
        "result": result,
        "error_type": result.get("error_type") if not ok else None,
    }

def _sanitize_params(params: dict, entry) -> dict:
    """Strip blocked params, validate against signature."""
    clean = dict(params)

    # Always strip user_email (injected server-side)
    clean.pop("user_email", None)

    # Strip/force blocked params
    for param_name, forced_value in BLOCKED_PARAMS.items():
        if forced_value is not None:
            if param_name in inspect.signature(entry.callable).parameters:
                clean[param_name] = forced_value
        else:
            clean.pop(param_name, None)

    # Validate: reject unknown params
    sig = inspect.signature(entry.callable)
    valid_params = set(sig.parameters.keys()) - {"user_email"}
    unknown = set(clean.keys()) - valid_params
    if unknown:
        raise HTTPException(400, f"Unknown params: {sorted(unknown)}. Valid: {sorted(valid_params)}")

    # Validate: check required params
    for pname, p in sig.parameters.items():
        if pname == "user_email":
            continue
        if p.default is inspect.Parameter.empty and pname not in clean:
            raise HTTPException(400, f"Missing required param: '{pname}'")

    return clean

@handle_http_errors
def _http_dispatch(fn: Callable, params: dict) -> dict:
    """Call the unwrapped function with HTTP-safe error handling."""
    return fn(**params)
```

### Step 5: Registry Discovery — `routes/agent_api.py`

```python
@router.get("/registry")
async def agent_registry(
    tier: str = None,
    category: str = None,
    user: dict = Depends(get_agent_user),
):
    registry = get_registry()
    functions = {}
    for name, entry in registry.items():
        if tier and entry.tier != tier:
            continue
        if category and entry.category != category:
            continue
        functions[name] = _build_schema(name, entry)
    return {"functions": functions, "total": len(functions)}

def _build_schema(name: str, entry: AgentFunction) -> dict:
    sig = inspect.signature(entry.callable)
    params = {}
    for pname, p in sig.parameters.items():
        if pname == "user_email":
            continue
        if pname in BLOCKED_PARAMS:
            continue  # hide blocked params from schema
        param_info = {"type": _type_name(p.annotation)}
        if p.default is not inspect.Parameter.empty:
            param_info["default"] = p.default
        else:
            param_info["required"] = True
        params[pname] = param_info
    return {
        "tier": entry.tier,
        "category": entry.category,
        "description": (entry.callable.__doc__ or "").strip().split("\n")[0],
        "read_only": entry.read_only,
        "params": params,
    }
```

### Step 6: Client Library — `risk_client/`

```python
"""Portfolio Risk Analysis API client for agent code execution."""

import os
import requests

class AgentAPIError(Exception):
    """Raised by call_or_raise when the API returns an error."""
    def __init__(self, function, error, error_type=None):
        self.function = function
        self.error = error
        self.error_type = error_type
        super().__init__(f"{function}: {error}")

class RiskClient:
    def __init__(self, base_url=None, api_key=None):
        self.base_url = (base_url or os.environ.get("RISK_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("RISK_API_KEY", "")
        if not self.base_url:
            raise ValueError("RISK_API_URL required (env var or constructor)")
        if not self.api_key:
            raise ValueError("RISK_API_KEY required (env var or constructor)")
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.api_key}"

    def call(self, function: str, **params) -> dict:
        """Call a registered function. Returns the response envelope."""
        resp = self._session.post(
            f"{self.base_url}/api/agent/call",
            json={"function": function, "params": params},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def call_or_raise(self, function: str, **params) -> dict:
        """Call a function and raise AgentAPIError on error responses."""
        envelope = self.call(function, **params)
        if not envelope.get("ok"):
            result = envelope.get("result", {})
            raise AgentAPIError(
                function=function,
                error=result.get("error", "Unknown error"),
                error_type=envelope.get("error_type"),
            )
        return envelope["result"]

    def registry(self, tier=None, category=None) -> dict:
        """Discover available functions."""
        params = {}
        if tier: params["tier"] = tier
        if category: params["category"] = category
        resp = self._session.get(
            f"{self.base_url}/api/agent/registry",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Tier 1: All 33 Phase 1 allowlist convenience methods ---

    # Positions
    def get_positions(self, **kw): return self.call("get_positions", **kw)

    # Risk
    def get_risk_analysis(self, **kw): return self.call("get_risk_analysis", **kw)
    def get_risk_score(self, **kw): return self.call("get_risk_score", **kw)
    def get_risk_profile(self, **kw): return self.call("get_risk_profile", **kw)
    def get_leverage_capacity(self, **kw): return self.call("get_leverage_capacity", **kw)
    def monitor_hedge_positions(self, **kw): return self.call("monitor_hedge_positions", **kw)

    # Performance
    def get_performance(self, **kw): return self.call("get_performance", **kw)

    # Optimization & Scenarios
    def run_optimization(self, **kw): return self.call("run_optimization", **kw)
    def get_efficient_frontier(self, **kw): return self.call("get_efficient_frontier", **kw)
    def run_whatif(self, **kw): return self.call("run_whatif", **kw)
    def run_backtest(self, **kw): return self.call("run_backtest", **kw)
    def compare_scenarios(self, **kw): return self.call("compare_scenarios", **kw)

    # Analysis (stateless — required params surfaced)
    def analyze_stock(self, ticker, **kw): return self.call("analyze_stock", ticker=ticker, **kw)
    def analyze_option_chain(self, symbol, expiry, **kw): return self.call("analyze_option_chain", symbol=symbol, expiry=expiry, **kw)
    def analyze_option_strategy(self, legs, **kw): return self.call("analyze_option_strategy", legs=legs, **kw)

    # Analysis (user-scoped)
    def get_trading_analysis(self, **kw): return self.call("get_trading_analysis", **kw)
    def get_factor_analysis(self, **kw): return self.call("get_factor_analysis", **kw)
    def get_factor_recommendations(self, **kw): return self.call("get_factor_recommendations", **kw)
    def preview_rebalance_trades(self, **kw): return self.call("preview_rebalance_trades", **kw)
    def check_exit_signals(self, ticker, **kw): return self.call("check_exit_signals", ticker=ticker, **kw)

    # Income
    def get_income_projection(self, **kw): return self.call("get_income_projection", **kw)
    def suggest_tax_loss_harvest(self, **kw): return self.call("suggest_tax_loss_harvest", **kw)

    # Transactions (read-only)
    def list_transactions(self, **kw): return self.call("list_transactions", **kw)
    def list_ingestion_batches(self, **kw): return self.call("list_ingestion_batches", **kw)
    def inspect_transactions(self, **kw): return self.call("inspect_transactions", **kw)
    def list_flow_events(self, **kw): return self.call("list_flow_events", **kw)
    def list_income_events(self, **kw): return self.call("list_income_events", **kw)
    def transaction_coverage(self, **kw): return self.call("transaction_coverage", **kw)

    # Market data (stateless)
    def get_quote(self, tickers, **kw): return self.call("get_quote", tickers=tickers, **kw)
    def get_futures_curve(self, symbol, **kw): return self.call("get_futures_curve", symbol=symbol, **kw)

    # Market (user-scoped) — deferred until FMP helper stdout fix
    # def get_portfolio_news(self, **kw): return self.call("get_portfolio_news", **kw)
    # def get_portfolio_events_calendar(self, **kw): return self.call("get_portfolio_events_calendar", **kw)

    # Baskets (read-only)
    def list_baskets(self, **kw): return self.call("list_baskets", **kw)
    def get_basket(self, name, **kw): return self.call("get_basket", name=name, **kw)

    # Trading (read-only)
    def get_orders(self, **kw): return self.call("get_orders", **kw)

    # --- Tier 2: Building block methods (added in Phase 1b) ---
    # Uncomment these when Phase 1b building blocks are registered.
    # def get_price_series(self, tickers, **kw): ...
    # def get_returns_series(self, tickers, **kw): ...
    # def get_portfolio_weights(self, **kw): ...
    # def get_correlation_matrix(self, tickers, **kw): ...
    # def compute_metrics(self, **kw): ...
    # def run_stress_test(self, **kw): ...
    # def run_monte_carlo(self, **kw): ...
    # def get_factor_exposures(self, tickers, **kw): ...
    # def fetch_fmp_data(self, endpoint, **kw): ...
    # def get_dividend_history(self, tickers, **kw): ...
```

### Step 7: Wire into `app.py` + `settings.py`

- `app.py`: `app.include_router(agent_api_router, prefix="/api/agent", tags=["agent"])`
- `settings.py`:
  ```python
  AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
  AGENT_API_ALLOW_WRITES = os.environ.get("AGENT_API_ALLOW_WRITES", "").lower() == "true"
  ```

---

## Phase 1b — Tier 2 Building Blocks

Same as v2. Functions use `@handle_http_errors` (not `@handle_mcp_errors`). Stable param names matching client convenience methods exactly.

| # | Function | Source | Category |
|---|----------|--------|----------|
| 1 | `get_price_series(tickers, start_date, end_date, period)` | `providers/price_service.py` | data |
| 2 | `get_returns_series(tickers, start_date, end_date, period)` | `portfolio_risk_engine/portfolio_risk.py` | data |
| 3 | `get_portfolio_weights(portfolio_name)` | `core/run_portfolio_risk.py` | data |
| 4 | `get_correlation_matrix(tickers, period)` | `portfolio_risk_engine/portfolio_risk.py` | data |
| 5 | `compute_metrics(returns, benchmark)` | `core/performance_metrics_engine.py` | compute |
| 6 | `run_stress_test(scenario, positions, weights)` | `portfolio_risk_engine/stress_testing.py` | compute |
| 7 | `run_monte_carlo(returns, weights, simulations, horizon)` | `portfolio_risk_engine/monte_carlo.py` | compute |
| 8 | `get_factor_exposures(tickers, period)` | `portfolio_risk_engine/` | data |
| 9 | `fetch_fmp_data(endpoint, params)` | `fmp/client.py` | data |
| 10 | `get_dividend_history(tickers, period)` | `providers/` | data |

---

## Phase 2 — Mutations

Gated behind `AGENT_API_ALLOW_WRITES=true`. Stricter rate limit (10/minute).

| Function | Category | Notes |
|----------|----------|-------|
| `preview_trade` | trading | Read-only preview — could move to Phase 1 |
| `preview_basket_trade` | trading | Read-only preview |
| `preview_futures_roll` | trading | Read-only preview |
| `preview_option_trade` | trading | Read-only preview |
| `execute_trade` | trading | Real money |
| `cancel_order` | trading | |
| `execute_basket_trade` | trading | Real money |
| `execute_futures_roll` | trading | Real money |
| `execute_option_trade` | trading | Real money |
| `create_portfolio` | portfolio_mgmt | |
| `delete_portfolio` | portfolio_mgmt | |
| `update_portfolio_accounts` | portfolio_mgmt | |
| `account_activate` | portfolio_mgmt | |
| `account_deactivate` | portfolio_mgmt | |
| `set_risk_profile` | risk | |
| `set_target_allocation` | allocation | Needs user_email refactor first |
| `create_basket` | baskets | |
| `update_basket` | baskets | |
| `delete_basket` | baskets | |
| `create_basket_from_etf` | baskets | |
| `fetch_provider_transactions` | transactions | |
| `refresh_transactions` | transactions | |

## Phase 3 — Multi-User

**Superseded 2026-04-22.** This Phase 3 design was **not** implemented.

Multi-user Agent API auth shipped via the gateway-signed HMAC-SHA256 user-claim design in `docs/planning/AGENT_API_SIGNED_USER_CLAIM_PLAN.md`, reusing the existing `routes/internal_resolver.py` signing pattern instead of creating a parallel DB-backed key-management surface.

| Original step | Original proposal | Status |
|------|------|------|
| 3.1 | DB-backed `agent_api_keys` table | Superseded — no DB table was added |
| 3.2 | Key management endpoints | Superseded — replaced by gateway-signed claim headers |
| 3.3 | Per-user scoping (already works via user_email injection) | Superseded — now enforced by signed `user_id` + `user_email` claims |

Shipped implementation commits:
- `risk_module`: `2fe96075`, `6e9cc689`, `6d2a131f`
- `AI-excel-addin`: `5099f18`, `b16e8e2`, `985d30a`

Ops runbook: `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md`

---

## Files Summary

| Action | File | Phase | What |
|--------|------|-------|------|
| **Edit** | `mcp_tools/common.py` | 1 | Add `handle_http_errors`, `_classify_error_type` |
| **Create** | `services/agent_registry.py` | 1 | Allowlisted registry (28 user-scoped + 5 stateless = 33 Tier 1 read-only) |
| **Create** | `routes/agent_api.py` | 1 | RPC + discovery + bearer auth + param sanitization |
| **Create** | `risk_client/__init__.py` | 1 | Client library |
| **Create** | `risk_client/pyproject.toml` | 1 | Package metadata |
| **Create** | `services/agent_building_blocks.py` | 1b | 10 Tier 2 wrappers |
| **Create** | `tests/routes/test_agent_api.py` | 1 | Endpoint tests |
| **Create** | `tests/test_risk_client.py` | 1 | Client tests |
| **Create** | `tests/services/test_agent_building_blocks.py` | 1b | Building block tests |
| **Edit** | `app.py` | 1 | Register router (1 line) |
| **Edit** | `settings.py` | 1 | Add 2 env vars |

## Security

- `user_email` ALWAYS injected server-side — stripped from client params
- Bearer-only auth, `secrets.compare_digest()` (timing-safe)
- **Fail closed**: empty `AGENT_API_KEY` → HTTP 503 (not silently open)
- **No cookie fallback** in any mode
- **Read-only default**: mutations require `AGENT_API_ALLOW_WRITES=true`
- **Param sanitization**: `backfill_path` stripped, `output` forced to `"inline"`, `debug_inference` forced to `False`, blocked params hidden from discovery schema
- **Explicit allowlist**: 33 curated functions, NOT the full 73
- **Permanently excluded**: file-path tools, normalizer builder, admin config, implicit-user tools
- **Thread-safe**: `handle_http_errors` does not touch `sys.stdout`

## Verification

1. **Auth**: Empty key → 503. No bearer header → 401. Wrong key → 401. Valid key → 200.
2. **Read-only gate**: Mutation function → 403 when `ALLOW_WRITES` is false.
3. **Param sanitization**: `backfill_path` → stripped. `output` → forced `"inline"`. `debug_inference` → forced `False`. Unknown param → 400. Missing required → 400.
4. **User injection**: `user_email` stripped from client params, injected from auth. Verified absent from discovery schema.
5. **Error envelope**: Business error → `{"ok": false, "error_type": "business"}`. Infra → `"infrastructure"`. Auth → `"auth"`.
6. **No stdout swap**: Two concurrent `/api/agent/call` requests → stdout unmodified (verify `sys.stdout` is not `sys.stderr` after concurrent calls).
7. **Discovery**: `GET /registry` returns 33 functions. `?tier=building_block` returns 0 until Phase 1b. Blocked params hidden.
8. **Client**: `call()` returns envelope. `call_or_raise()` raises `AgentAPIError`. Constructor rejects empty URL/key.
9. **Integration**: `RiskClient.get_positions()` returns same data shape as MCP `get_positions()`.
10. **Exclusion**: Calling excluded function name → 404.
