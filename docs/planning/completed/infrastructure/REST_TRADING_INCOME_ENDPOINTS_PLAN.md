# REST Endpoints for Trading Analysis & Income Projection

**Status:** COMPLETE (2026-03-05, commit `b6f99dfb`)

## Context
MCP tools `get_trading_analysis()` and `get_income_projection()` provide rich portfolio analysis but are only accessible to Claude agents. The frontend talks REST. Adding thin REST wrappers lets us build frontend tabs for trade history and income projections. Market Intelligence already has a REST endpoint (`GET /api/positions/market-intelligence`) — no work needed there.

## Approach
Follow the existing pattern from `routes/positions.py` lines 303-360: cookie auth → call backend function → return JSON. Call MCP tool functions directly (they already encapsulate user resolution, data fetching, and formatting). Thin params — expose only what the frontend needs now.

### Data flow

**Trading Analysis:** `get_trading_analysis()` → `TradingAnalyzer.run_full_analysis()` → `FullAnalysisResult` (result object in `trading_analysis/models.py:573`) → `.to_api_response()` returns serialized dict.

**Income Projection:** `get_income_projection()` → `build_income_projection()` → raw dict → `_format_full()` helper returns serialized dict.

Both MCP functions return `{"status": "success", ...data}` dicts. The REST route checks `status` and maps errors to HTTP status codes.

### Key design decisions (from Codex review)

1. **`@handle_mcp_errors` swallows exceptions** — The MCP decorator catches all exceptions and returns `{"status": "error", "error": "..."}` as a normal dict (HTTP 200). The route's `try/except` will NOT fire. Instead, check `result.get("status") == "error"` after the call and raise `HTTPException(500)`.

2. **`projection_months` max = 24** — `mcp_tools/income.py:239` hard-clamps to `min(projection_months, 24)`. The Query validator must match: `le=24`, not `le=60`.

3. **Email validation** — `auth_service.get_user_by_session()` can return a user dict with empty email. Add explicit `if not user.get("email")` guard before calling MCP function (matches `routes/realized_performance.py` pattern).

## Changes

### 1. Create `routes/trading.py`

```python
"""Trading Analysis API Route."""
from fastapi import APIRouter, Query, Request, HTTPException
from services.auth_service import auth_service
from utils.logging import portfolio_logger, log_error

trading_router = APIRouter(prefix="/api/trading", tags=["trading"])

@trading_router.get("/analysis")
async def get_trading_analysis_endpoint(
    request: Request,
    start_date: str | None = Query(None, description="Start date YYYY-MM-DD"),
    end_date: str | None = Query(None, description="End date YYYY-MM-DD"),
):
    """Return trading analysis for the authenticated user."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="User email not found")
    try:
        from mcp_tools.trading_analysis import get_trading_analysis
        result = get_trading_analysis(
            user_email=user["email"],
            format="full",
            start_date=start_date,
            end_date=end_date,
        )
        if isinstance(result, dict) and result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Trading analysis failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        portfolio_logger.error(f"Trading analysis failed: {e}")
        log_error("trading_api", "analysis", e)
        raise HTTPException(status_code=500, detail="Failed to generate trading analysis")
```

**Why `format="full"`:** The frontend needs structured data (scorecard, timing, behavioral patterns, income) to render tabs. Summary is too condensed, agent format adds flags the frontend doesn't consume.

**Params exposed:** `start_date`, `end_date` only. Source defaults to "all", segment to "all". Add more later if the frontend needs filtering.

### 2. Create `routes/income.py`

```python
"""Income Projection API Route."""
from fastapi import APIRouter, Query, Request, HTTPException
from services.auth_service import auth_service
from utils.logging import portfolio_logger, log_error

income_router = APIRouter(prefix="/api/income", tags=["income"])

@income_router.get("/projection")
async def get_income_projection_endpoint(
    request: Request,
    projection_months: int = Query(12, ge=1, le=24, description="Forward projection window in months"),
):
    """Return income projection for the authenticated user."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="User email not found")
    try:
        from mcp_tools.income import get_income_projection
        result = get_income_projection(
            user_email=user["email"],
            projection_months=projection_months,
            format="full",
        )
        if isinstance(result, dict) and result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Income projection failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        portfolio_logger.error(f"Income projection failed: {e}")
        log_error("income_api", "projection", e)
        raise HTTPException(status_code=500, detail="Failed to generate income projection")
```

**Params exposed:** `projection_months` only (with validation: 1-24, matching tool's hard clamp). Format defaults to "full" so the frontend gets monthly breakdown, calendar, and contributors.

### 3. Register routers in `app.py`

Near the existing router registrations (~line 5655-5665), add:

```python
from routes.trading import trading_router
from routes.income import income_router

app.include_router(trading_router)
app.include_router(income_router)
```

### 4. Update TODO

Remove the "Frontend: REST Endpoint for Trading Analysis" and "Frontend: REST Endpoint for Income Projection" backlog items. Mark Market Intelligence as already done.

## Codex Review History

- **Review 1 (2026-03-05)**: FAIL. 5 findings: (1) `@handle_mcp_errors` swallows exceptions → HTTP 200 for errors, (2) `projection_months` le=60 but tool clamps to 24, (3) email validation gap, (4) stdout mutation side effect (existing, not blocking), (5) error mapping less robust than realized_performance route. All addressed in v2.

## Files Modified

| File | Change |
|------|--------|
| `routes/trading.py` | **NEW** — `GET /api/trading/analysis` |
| `routes/income.py` | **NEW** — `GET /api/income/projection` |
| `app.py` | Import + register 2 new routers |
| `docs/planning/TODO.md` | Remove completed backlog items |

## Verification

1. Start backend: `make dev`
2. Test trading analysis:
   ```
   curl -b "session_id=<valid>" http://localhost:8000/api/trading/analysis
   curl -b "session_id=<valid>" "http://localhost:8000/api/trading/analysis?start_date=2025-01-01&end_date=2025-12-31"
   ```
3. Test income projection:
   ```
   curl -b "session_id=<valid>" http://localhost:8000/api/income/projection
   curl -b "session_id=<valid>" "http://localhost:8000/api/income/projection?projection_months=6"
   ```
4. Verify 401 on unauthenticated requests
5. Verify existing endpoints still work (no regression)
