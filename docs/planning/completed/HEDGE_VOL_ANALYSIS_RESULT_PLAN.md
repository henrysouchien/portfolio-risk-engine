# Fix: Service self-loads analysis_result for portfolio vol

## Context

`recommend_portfolio_offsets` needs `analysis_result` for valid `volatility_annual`. Without it, `build_portfolio_view` with bare weights → global `dropna()` → zero common observations for mixed-vintage tickers → NaN vol.

## Architecture

The service should be self-sufficient. MCP tools are thin pass-throughs — they should not contain portfolio loading logic.

## Fix

### 1. Service: `services/factor_intelligence_service.py`

Add `user_id: Optional[int] = None` to `recommend_portfolio_offsets`. When `analysis_result is None` and `user_id is not None`, self-load at the top of the method before the path 1/path 2 branch:

```python
def recommend_portfolio_offsets(
    self,
    *,
    weights: Dict[str, float],
    ...
    analysis_result: Optional[Any] = None,
    user_id: Optional[int] = None,
    ...
):
    # Self-load analysis_result when not provided
    if analysis_result is None and user_id is not None:
        try:
            from services.portfolio.result_cache import get_analysis_result_snapshot
            from services.portfolio.workflow_cache import (
                get_factor_proxies_snapshot,
                get_portfolio_snapshot,
                get_risk_limits_snapshot,
            )
            from services.portfolio_service import PortfolioService
            _pd = get_portfolio_snapshot(user_id, "CURRENT_PORTFOLIO")
            _pd.stock_factor_proxies = get_factor_proxies_snapshot(
                user_id, "CURRENT_PORTFOLIO", _pd, allow_gpt=True,
            )
            _pd.refresh_cache_key()
            _rl, _ = get_risk_limits_snapshot(user_id, "CURRENT_PORTFOLIO")
            analysis_result = get_analysis_result_snapshot(
                user_id=user_id, portfolio_name="CURRENT_PORTFOLIO",
                portfolio_data=_pd, risk_limits_data=_rl,
                performance_period="1M", use_cache=True,
                builder=lambda: PortfolioService(cache_results=True).analyze_portfolio(
                    _pd, _rl, performance_period="1M",
                ),
            )
        except Exception as exc:
            logger.warning("recommend_portfolio_offsets: self-load analysis_result failed: %s", exc)

    # existing path 1/path 2 logic follows...
```

### 2. MCP tool: `mcp_tools/factor_intelligence.py` line ~1105

Pass `user_id` through. Resolve it from `user_email` (already available):

```python
# resolve user_id for service
_uid = None
try:
    from utils.user_resolution import resolve_user_id as _resolve_uid
    from settings import get_default_user
    _uid = _resolve_uid(user_email or get_default_user())
except Exception:
    pass

result = service.recommend_portfolio_offsets(
    weights=weights,
    user_id=_uid,
    ...existing params...
)
```

### 3. REST endpoint: `routes/factor_intelligence.py` line ~237

One line — user_id is already available from auth:

```python
result = await run_in_threadpool(
    service.recommend_portfolio_offsets,
    weights=rec_request.weights,
    user_id=int(user["user_id"]),
    ...existing params...
)
```

### 4. Optional: refactor `build_ai_recommendations`

`build_ai_recommendations` (lines 383-405) has the same loading logic inline. It already passes `analysis_result` so the self-load won't fire — but the inline code could be removed and replaced with just passing `user_id` to let the service handle it. Reduces duplication. Can be done separately.

## Files

| File | Change |
|------|--------|
| `services/factor_intelligence_service.py` | Add `user_id` param + self-load block |
| `mcp_tools/factor_intelligence.py` | Resolve user_id, pass to service (~5 lines) |
| `routes/factor_intelligence.py` | Pass `user_id=int(user["user_id"])` (1 line) |

## Verification

1. `python3 -m pytest tests/services/test_factor_intelligence_service.py tests/core/test_factor_recs_agent_snapshot.py -x -q`
2. Direct:
```python
from mcp_tools.factor_intelligence import get_factor_recommendations
result = get_factor_recommendations(mode='portfolio', format='full')
print(result['diagnosis']['portfolio_volatility'])  # ~0.077
```
