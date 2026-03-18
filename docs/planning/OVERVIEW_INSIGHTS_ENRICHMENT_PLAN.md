# Overview Card AI Insights — Enrichment Pass

**Status:** Draft (v1)
**Date:** 2026-03-18
**Depends on:** OVERVIEW_CARD_INSIGHTS_PLAN.md (v10, implemented)

## Goal

The 6 overview cards now all have AI Insights wired up, but most are thin — single flags that only fire on warnings. This plan enriches all 6 cards with richer insights drawn from data we already compute but don't surface.

## Design Principle

Each card answers one question. The insight should add **context to the number** the user is looking at — not repeat it, not warn about something unrelated.

| Card | Question | Insight Should Say |
|---|---|---|
| Total Portfolio Value | "What do I own?" | What it earns (income/yield) |
| YTD Return | "How am I doing?" | How consistently (win rate, streaks) |
| Risk Score | "Am I safe?" | What's driving risk (top factor, recommendation) |
| Sharpe Ratio | "Am I getting paid for risk?" | How it compares (benchmark Sharpe, Sortino) |
| Alpha Generation | "Am I beating the market?" | How much divergence (tracking error, capture) |
| Concentration | "Am I diversified?" | What kind of diversification (factor vs stock-specific) |

## Current State

Each card gets its insight from flag generators called inside `build_metric_insights()`. Flags are mapped to card IDs via `_*_FLAG_MAP` dicts. The builder picks the highest-severity flag as `aiInsight` and the second as `marketContext`.

**Data already loaded by the metric-insights flow:**
- Position result (positions, sector allocation, cash, leverage)
- Risk analysis result (factor betas, variance decomposition, HHI, VaR, allocations)
- Risk score result (component scores, recommendations, risk factors, violations)
- Performance result — hypothetical 1-year (returns, Sharpe, Sortino, drawdown, monthly stats, income metrics)
- Realized performance result (returns, alpha, beta, income, monthly stats, win rate, P&L)

## Plan

### Theme 1: Income & Yield → Total Portfolio Value card

**New flags in `core/position_flags.py`** (extend existing generator — it already receives position data):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `portfolio_income_yield` | Realized snapshot has `income.yield_on_value > 0` | info | "Portfolio yields {x}% annually (${projected}/yr projected)" |
| `high_income_yield` | yield_on_value > 4% | success | "Strong income: {x}% yield (${projected}/yr)" |

**Data source:** The realized performance snapshot has `income.total`, `income.yield_on_value_pct`, `income.projected_annual`. BUT — the position flag loader doesn't currently have access to the realized performance snapshot.

**Wiring approach:** Rather than passing the realized snapshot cross-loader, add these as new flags in the **alpha flag loader** (which already loads realized performance), mapped to `totalValue`:

```python
_INCOME_FLAG_MAP = {
    "portfolio_income_yield": "totalValue",
    "high_income_yield": "totalValue",
}
```

Generate income flags from the realized snapshot inside `_load_alpha_flag_insights()`, since it already has the realized result. New generator: `generate_income_flags(snapshot)` in `core/income_insight_flags.py`.

### Theme 2: Return Quality → YTD Return card

**New flags in `core/performance_flags.py`** (extend existing generator — it already receives the performance snapshot):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `high_win_rate` | win_rate > 65% AND period >= 1yr | success | "Positive {x}% of months over the past year" |
| `low_win_rate` | win_rate < 40% AND period >= 1yr | info | "Only {x}% of months were positive" |
| `strong_recent_month` | best_month > +5% | info | "Best month was +{x}% ({date})" |
| `harsh_drawdown_month` | worst_month < -8% | warning | "Worst month was {x}% ({date})" |

**Data source:** `snapshot["returns"]["win_rate_pct"]`, `snapshot["returns"]["best_month_pct"]`, `snapshot["returns"]["worst_month_pct"]`. Already in the hypothetical performance snapshot.

These go directly into the existing `generate_performance_flags()` function and map to `ytdReturn` via `_PERF_FLAG_MAP`.

### Theme 3: Risk Drivers → Risk Score card

**New flags in `core/risk_score_flags.py`** (extend existing generator):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `top_risk_factor` | Factor variance > 60% of total | info | "{factor} exposure drives {x}% of portfolio risk" |
| `high_idiosyncratic` | Idiosyncratic variance > 50% | info | "{x}% of risk is stock-specific — diversification has limited effect" |
| `top_recommendation` | recommendations list non-empty | info | "Suggested: {first recommendation}" |

**Data source:** The risk score snapshot has `risk_factors` (ranked list) and `recommendations` (list of suggestions). The risk analysis result has `variance_decomposition` with `factor_pct` / `idiosyncratic_pct`.

**Challenge:** `_load_risk_score_flag_insights()` calls `generate_risk_score_flags(risk_snapshot)` but the risk snapshot doesn't include variance decomposition — that's in the `analysis_result`. We need to either:
- Pass `analysis_result.get_agent_snapshot()` to the flag generator (adds a param)
- Or extract what we need from the risk score snapshot's `risk_factors` field (already has ranked factors)

**Approach:** Use `risk_factors` from the risk score snapshot for `top_risk_factor` (it already ranks factors by impact). Use `recommendations` for `top_recommendation`. For `high_idiosyncratic`, pass the analysis summary which is already loaded.

### Theme 4: Risk-Adjusted Quality → Sharpe Ratio card

**New flags in `core/performance_flags.py`** (extend existing — same snapshot):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `good_sharpe` | Sharpe >= 1.0 AND period >= 1yr | success | "Sharpe {x} — strong risk-adjusted returns" |
| `excellent_sharpe` | Sharpe >= 1.5 AND period >= 1yr | success | "Sharpe {x} — excellent risk-adjusted returns" |
| `sharpe_vs_benchmark` | benchmark Sharpe available AND delta > 0.2 | success | "Sharpe {x} vs benchmark {bm} — earning premium" |
| `sharpe_vs_benchmark_lag` | benchmark Sharpe available AND delta < -0.2 | info | "Sharpe {x} vs benchmark {bm} — underperforming on risk-adjusted basis" |
| `good_sortino` | Sortino > 1.5 | info | "Sortino {x} — downside risk well managed" |

**Data source:** `snapshot["risk"]["sharpe_ratio"]`, `snapshot["risk"]["sortino_ratio"]`, `snapshot["benchmark"]["beta"]`. Benchmark Sharpe is available via the portfolio summary adapter (`benchmarkSharpe`) but may need to be passed through.

Map to `sharpeRatio` via `_PERF_FLAG_MAP`.

### Theme 5: Benchmark Intelligence → Alpha Generation card

**New flags in `core/alpha_flags.py`** (extend existing):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `high_tracking_error` | tracking_error > 10% | info | "Tracking error {x}% — portfolio diverges significantly from {benchmark}" |
| `low_tracking_error` | tracking_error < 3% | info | "Tracking error {x}% — closely tracking {benchmark}" |
| `asymmetric_capture` | up_capture > 1.0 AND down_capture < 1.0 | success | "Captures {up}% of gains, only {down}% of losses — favorable asymmetry" |

**Data source:** Tracking error is in the realized snapshot at `benchmark.tracking_error` or in hypothetical at `benchmark.tracking_error_pct`. Up/down capture ratios are in realized performance (`risk_adjusted.up_capture_ratio`, `risk_adjusted.down_capture_ratio`).

These are **context flags** (severity: `success`) that supplement the primary alpha flag. They surface as `marketContext`.

### Theme 6: Diversification Quality → Concentration card

**New flags in `core/concentration_flags.py`** (extend existing):

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `factor_dominated` | factor_variance_pct > 70% | info | "{x}% factor risk — returns largely driven by market/sector exposure" |
| `stock_specific_heavy` | idiosyncratic_variance_pct > 50% | info | "{x}% stock-specific risk — individual holdings drive outcomes" |
| `many_sectors` | sector_count >= 8 | success | "Diversified across {n} sectors" |

**Data source:** `factor_variance_pct` and `idiosyncratic_variance_pct` are in the risk analysis result. Sector count is derivable from position data.

**Challenge:** Same as Theme 3 — the concentration flag generator currently only receives the risk score snapshot, not the analysis result. Need to pass variance decomposition data.

**Approach:** Extend `generate_concentration_flags()` to accept an optional `analysis_summary` dict (from `analysis_result.get_summary()`) which includes `herfindahl`, `factor_variance_pct`, `idiosyncratic_variance_pct`. These are **context flags** that supplement the primary concentration flag.

## Implementation Order

All themes extend existing flag generators and existing loaders. No new loaders needed.

1. **Theme 4: Sharpe** — biggest gap (almost always empty), easiest (extends performance_flags, same snapshot)
2. **Theme 2: YTD Return** — extends performance_flags, same snapshot
3. **Theme 5: Alpha** — extends alpha_flags, same snapshot (tracking error + capture ratios)
4. **Theme 3: Risk Score** — extends risk_score_flags (needs risk_factors/recommendations from snapshot)
5. **Theme 6: Concentration** — extends concentration_flags (needs analysis_summary param addition)
6. **Theme 1: Income** — new file (needs income data from realized snapshot, wired through alpha loader)

## Files Changed

| File | Change |
|---|---|
| `core/performance_flags.py` | Add Sharpe quality flags (Theme 4) + win rate/month flags (Theme 2) |
| `core/alpha_flags.py` | Add tracking error + capture ratio context flags (Theme 5) |
| `core/risk_score_flags.py` | Add top risk factor + recommendation flags (Theme 3) |
| `core/concentration_flags.py` | Add factor/idiosyncratic split + sector count flags (Theme 6) |
| `core/income_insight_flags.py` | **NEW** — income yield flags (Theme 1) |
| `mcp_tools/metric_insights.py` | Add `_INCOME_FLAG_MAP`, wire income flags in alpha loader, pass analysis_summary to concentration generator |
| `frontend/.../useOverviewMetrics.ts` | No change needed — already wired for all 6 card IDs |
| `tests/core/test_performance_flags.py` | Extend with Sharpe + return quality tests |
| `tests/core/test_alpha_flags.py` | Extend with tracking error + capture tests |
| `tests/core/test_risk_score_flags.py` | Extend with risk factor + recommendation tests |
| `tests/core/test_concentration_flags.py` | Extend with factor split + sector tests |
| `tests/core/test_income_insight_flags.py` | **NEW** — income flag tests |

## Risks / Notes

- **No new data fetches** — all data is already loaded by existing metric-insights loaders. We're just reading more fields from the same snapshots.
- **Flag priority** — new flags should generally be `info` or `success` severity so they don't override existing `warning`/`error` flags. Warnings/errors are more important (violations, deep drawdowns, etc.). The new flags enrich the insight when nothing is wrong.
- **Context slots** — `build_metric_insights()` shows top flag as `aiInsight` and second as `marketContext`. New context flags supplement the primary. If a warning is primary, a context flag adds useful detail.
- **Threshold tuning** — initial thresholds based on common portfolio management benchmarks. May need adjustment after seeing real output.
- **Concentration + Risk Score need analysis_summary** — both currently only receive the risk score snapshot. The `analysis_result.get_summary()` is already loaded in the risk score loader and just needs to be passed through.
