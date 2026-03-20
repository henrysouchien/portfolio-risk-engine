# Overview Card AI Insights — Alpha Generation & Concentration

**Status:** Draft (v10 — mode-aware alpha loader)
**Date:** 2026-03-18

## Problem

The overview page has 6 metric cards. Only 4 have AI Insights. **Alpha Generation** and **Concentration** are hardcoded to empty strings.

## v6 Failure & Root Cause

v6 was implemented and live-tested. Alpha insight showed "Trailing SPY by 2.0%" while the card displayed -7.9%.

Root cause: the metric-insights performance loader always runs **hypothetical** `analyze_performance()` with a hardcoded 1-year window. The frontend card uses **realized** performance for portfolios with linked accounts. Different calculation, different data, different number.

## How the Frontend Decides Mode

```
portfolio-summary resolver
  → resolverMap.performance()
    → if supported_modes includes 'performance_realized':
        POST /api/performance/realized → realized alpha
      else:
        POST /api/performance (hypothetical, 1-year default) → hypothetical alpha
  → PortfolioSummaryAdapter → alphaAnnual → card value
```

The alpha loader must make the **same mode decision**.

## Plan

### Step 1: Alpha Generation Flags — `core/alpha_flags.py` (new file)

`generate_alpha_flags(snapshot: dict) -> list[dict]`. Works on both realized and hypothetical snapshots — both have `benchmark.alpha_annual_pct`.

| Flag type | Trigger | Severity |
|---|---|---|
| `deep_underperformance` | alpha < -5% | warning |
| `strong_alpha` | alpha > +2% | success |
| `moderate_alpha` | 0 < alpha <= +2% | info |
| `negative_alpha` | alpha <= 0 | info |

Context: `high_beta_context` when beta > 1.3 (severity: `success`). Uses `"type"` key. Mutually exclusive primary via if/elif. Returns empty list when alpha is None.

### Step 2: Concentration Flags — `core/concentration_flags.py` (new file)

Same as v6. Unchanged — concentration has no mode split.

### Step 3: Wire into `metric_insights.py`

**Concentration** — inside existing `_load_risk_score_flag_insights()`. Same as v6.

**Alpha** — new `_load_alpha_flag_insights()` that branches on mode:

```python
def _load_alpha_flag_insights(*, user, user_id, portfolio_data, portfolio_service, use_cache):
    """Load alpha flags, matching the frontend's performance mode.

    Realized portfolios → analyze_realized_performance() (same as POST /api/performance/realized)
    Hypothetical portfolios → existing 1-year hypothetical analysis (same as POST /api/performance)
    """
    from core.alpha_flags import generate_alpha_flags
    from database import get_db_session
    from inputs.database_client import DatabaseClient
    from services.portfolio_scope import derive_supported_modes

    insights = {}

    # Derive supported_modes the same way the frontend gets it
    # (from GET /api/v2/portfolios → derive_supported_modes in portfolio_management.py:148)
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        portfolio_record = db_client.get_portfolio_record(user_id, "CURRENT_PORTFOLIO")
        portfolio_type = str((portfolio_record or {}).get("portfolio_type") or "manual").strip().lower()
        linked_accounts = db_client.get_portfolio_accounts(user_id, "CURRENT_PORTFOLIO") if portfolio_type != "manual" else []
    supported_modes = derive_supported_modes(portfolio_type, linked_accounts)
    use_realized = "performance_realized" in supported_modes

    if use_realized:
        # Realized path — same as routes/realized_performance.py:82
        from services.performance_helpers import load_portfolio_for_performance

        _, _, _, position_result = load_portfolio_for_performance(
            user_email=user,
            portfolio_name="CURRENT_PORTFOLIO",
            use_cache=use_cache,
            mode="realized",
            source="all",
        )
        realized_result = portfolio_service.analyze_realized_performance(
            position_result=position_result,
            user_email=user,
            benchmark_ticker="SPY",
            source="all",
        )
        if isinstance(realized_result, dict):
            from core.result_objects import RealizedPerformanceResult
            realized_result = RealizedPerformanceResult.from_analysis_dict(realized_result)
        snapshot = realized_result.get_agent_snapshot()
    else:
        # Hypothetical path — same 1-year window as POST /api/performance
        # (matches app.py:1725 which also forces 1-year default)
        import copy
        from datetime import date
        from dateutil.relativedelta import relativedelta

        perf_data = copy.deepcopy(portfolio_data)
        perf_data.end_date = date.today().isoformat()
        perf_data.start_date = (date.today() - relativedelta(years=1)).isoformat()
        perf_data.refresh_cache_key()

        perf_result = get_performance_result_snapshot(
            user_id=user_id,
            portfolio_name="CURRENT_PORTFOLIO",
            portfolio_data=perf_data,
            benchmark_ticker="SPY",
            cache_scope="summary_only",
            use_cache=use_cache,
            builder=lambda: portfolio_service.analyze_performance(
                perf_data, benchmark_ticker="SPY",
                include_attribution=False, include_optional_metrics=False,
            ),
        )
        snapshot = perf_result.get_agent_snapshot()

    alpha_flags = generate_alpha_flags(snapshot)
    for flag in alpha_flags:
        card_id = _ALPHA_FLAG_MAP.get(flag.get("type", ""))
        if card_id:
            insights.setdefault(card_id, []).append(flag)
    return insights
```

Submit as a new future in the ThreadPoolExecutor. Needs `user` (email) passed through — currently only `user_id` is passed to `_load_risk_score_flag_insights` and `_load_performance_flag_insights`, but `user` (email) is available in `build_metric_insights()` scope.

**Note on portfolio scoping:** Metric-insights hardcodes `CURRENT_PORTFOLIO` and caches by `user_id` only — this is a pre-existing limitation that applies to ALL existing insights (totalValue, riskScore, etc.), not specific to this feature. If the user selects a non-CURRENT portfolio on the frontend, all insights may mismatch. That's a separate architectural issue.

### Step 4: Frontend Wiring — `useOverviewMetrics.ts`

Replace hardcoded empty strings with `metricInsights["alphaGeneration"]` and `metricInsights["concentration"]`.

### Step 5: Tests

- `tests/core/test_alpha_flags.py` — boundaries (0, +2%, -5%), mutual exclusivity, missing data, context ordering
- `tests/core/test_concentration_flags.py` — boundaries (39/40/69/70), position_count=0, usable vs degenerate metadata
- `tests/mcp_tools/test_metric_insights.py` — extend:
  - Stub `get_db_session` + `DatabaseClient.get_portfolio_record` + `get_portfolio_accounts` AND mock `derive_supported_modes` to control the realized/hypothetical branch
  - Verify realized branch calls `load_portfolio_for_performance(mode="realized")` then `analyze_realized_performance`
  - Verify hypothetical branch calls `analyze_performance` with 1-year date override
  - Verify `alphaGeneration` and `concentration` keys in output
  - Fixture update: add `get_summary()` to analysis_result mock

## Files Changed

| File | Change |
|---|---|
| `core/alpha_flags.py` | **NEW** — `generate_alpha_flags()` |
| `core/concentration_flags.py` | **NEW** — `generate_concentration_flags()` |
| `mcp_tools/metric_insights.py` | Add flag maps, NEW `_load_alpha_flag_insights()` with mode branching, extend risk score loader for concentration |
| `frontend/.../useOverviewMetrics.ts` | Wire `metricInsights` for alpha + concentration cards |
| `tests/core/test_alpha_flags.py` | **NEW** |
| `tests/core/test_concentration_flags.py` | **NEW** |
| `tests/mcp_tools/test_metric_insights.py` | Extend + fixture update |

## Risks / Notes

- **Mode parity** — alpha loader derives `supported_modes` via `derive_supported_modes(portfolio_type, linked_accounts)` — the same function the `list_portfolios` endpoint uses (`portfolio_management.py:148`), which is what the frontend reads. Realized portfolios get realized alpha, hypothetical get hypothetical. Numbers match the card.
- **`load_portfolio_for_performance()`** — the realized branch uses this helper (same as the API route) for proper portfolio scope resolution, not raw `get_position_result_snapshot()`.
- **Hypothetical 1-year window** — the hypothetical branch uses the same 1-year override as `_load_performance_flag_insights()` and the `/api/performance` route (`app.py:1725`). This is correct for hypothetical portfolios.
- **Snapshot compatibility** — both `RealizedPerformanceResult.get_agent_snapshot()` and `PerformanceResult.get_agent_snapshot()` expose `benchmark.alpha_annual_pct` and `benchmark.beta`. `generate_alpha_flags()` works on both.
- **Performance** — realized analysis is cached via `PortfolioService(cache_results=True)`. The frontend triggers the realized call on page load, so the cache should be warm.
- **Thread safety** — `PortfolioService` already runs concurrently in the existing executor. Cache access is lock-guarded.
- **Concentration is clean** — uses risk score loader, no mode split needed.
- **Existing YTD/Sharpe insights unchanged** — stay on the existing hypothetical 1-year path.
