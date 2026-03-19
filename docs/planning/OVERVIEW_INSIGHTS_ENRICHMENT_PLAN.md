# Overview Card AI Insights — Enrichment Pass

**Status:** Draft (v3 — variance scale fix + priority model fix)
**Date:** 2026-03-18
**Depends on:** OVERVIEW_CARD_INSIGHTS_PLAN.md (v10, implemented)

## Goal

The 6 overview cards now all have AI Insights wired up, but most are thin — single flags that only fire on warnings. This plan enriches all 6 cards with richer insights drawn from data we already compute but don't surface.

## Design Principle

Each card answers one question. The insight should add **context to the number** the user is looking at.

| Card | Question | Insight Adds |
|---|---|---|
| Total Portfolio Value | "What do I own?" | What it earns (income/yield) |
| YTD Return | "How am I doing?" | How consistently (win rate, best/worst months) |
| Risk Score | "Am I safe?" | What's driving risk (top recommendation) |
| Sharpe Ratio | "Am I getting paid for risk?" | How it compares (benchmark Sharpe, Sortino) |
| Alpha Generation | "Am I beating the market?" | Return capture profile (up/down capture) |
| Concentration | "Am I diversified?" | What kind (factor vs stock-specific risk split) |

## Step 0: Expand `get_agent_snapshot()` — Prerequisite

Several fields are computed but not exposed in the agent snapshots. Add them before writing flag generators.

### PerformanceResult (`core/result_objects/performance.py`)

Add to `risk` section of `get_agent_snapshot()`:
```python
"tracking_error_pct": risk.get("tracking_error"),
"up_capture_ratio": risk_adjusted.get("up_capture_ratio"),
"down_capture_ratio": risk_adjusted.get("down_capture_ratio"),
```

Add to `benchmark` section:
```python
"sharpe_ratio": benchmark_comp.get("benchmark_sharpe"),
```

Add to `returns` section (extract dates from `self.monthly_returns` dict):
```python
"best_month_date": max(self.monthly_returns.items(), key=lambda x: x[1])[0] if self.monthly_returns else None,
"worst_month_date": min(self.monthly_returns.items(), key=lambda x: x[1])[0] if self.monthly_returns else None,
```

**Source fields (already computed):**
- `risk_metrics["tracking_error"]` — computed in `performance_metrics_engine.py:83`
- `risk_adjusted_returns["up_capture_ratio"]` / `["down_capture_ratio"]` — computed at lines 115-124
- `benchmark_comparison["benchmark_sharpe"]` — computed at line 306
- `monthly_returns` — dict with ISO date keys, already on the result object

### RealizedPerformanceResult (`core/result_objects/realized_performance.py`)

Add to `risk` section of `get_agent_snapshot()`:
```python
"tracking_error_pct": risk.get("tracking_error"),
"up_capture_ratio": risk_adjusted.get("up_capture_ratio"),
"down_capture_ratio": risk_adjusted.get("down_capture_ratio"),
```

Add to `benchmark` section:
```python
"sharpe_ratio": benchmark_comp.get("benchmark_sharpe"),
```

Add to `income` section:
```python
"projected_annual": income.projected_annual if income else None,
```

Best/worst month dates: extract from `self.monthly_returns` same as PerformanceResult.

## Priority Model

`build_metric_insights()` sorts flags by severity (error > warning > info > success), takes index 0 as `aiInsight` and index 1 as `marketContext`. To ensure new enrichment flags don't displace existing primary flags:

**All new enrichment flags use `success` severity** (lowest priority). This means:
- Existing `warning` flags (violations, deep drawdowns, concentration) always win → `aiInsight`
- Existing `info` flags (cash_drag, top5_concentration, low_sharpe) win over new flags → `aiInsight`
- New `success` flags surface as `marketContext` when a higher-priority flag exists
- New `success` flags become `aiInsight` only when no warnings or info flags fire — i.e., when the portfolio is healthy and the enrichment context is the most useful thing to show

**Exception:** `harsh_worst_month` (Theme 2) uses `warning` severity since a -8%+ month is genuinely concerning.

## Theme 1: Income & Yield → Total Portfolio Value card

**New file:** `core/income_insight_flags.py`

`generate_income_flags(snapshot: dict) -> list[dict]` — consumes realized performance snapshot.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `high_income_yield` | yield_on_value > 4% | success | "Strong income: {x}% yield (${total}/yr)" |
| `portfolio_income_yield` | 0 < yield_on_value <= 4% | success | "Portfolio yields {x}% annually" |

**Data source:** `snapshot["income"]["yield_on_value_pct"]` and `snapshot["income"]["projected_annual"]` (added in Step 0). Only fires for realized-mode portfolios (hypothetical has no income data).

**Wiring:** Generate inside `_load_alpha_flag_insights()` (which already loads the realized snapshot). Map via `_INCOME_FLAG_MAP` to `totalValue`. These are `success` severity so they won't override existing `warning` position flags (single_position_concentration, margin_usage) or `info` position flags (cash_drag, top5_concentration). Income flags surface as `marketContext` when position flags fire, or as `aiInsight` when no position flags fire.

## Theme 2: Return Quality → YTD Return card

**Extend:** `core/performance_flags.py` — add to existing `generate_performance_flags()`.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `high_win_rate` | win_rate > 65% AND period >= 1yr | success | "Positive {x}% of months over the past year" |
| `low_win_rate` | win_rate < 40% AND period >= 1yr | success | "Only {x}% of months were positive" |
| `strong_best_month` | best_month > +5% | success | "Best month: +{x}% ({date})" |
| `harsh_worst_month` | worst_month < -8% | warning | "Worst month: {x}% ({date})" |

**Data source:** `snapshot["returns"]["win_rate_pct"]`, `snapshot["returns"]["best_month_pct"]`, `snapshot["returns"]["worst_month_pct"]`, `snapshot["returns"]["best_month_date"]`, `snapshot["returns"]["worst_month_date"]` (dates added in Step 0).

**Mapping:** Add to `_PERF_FLAG_MAP` → `ytdReturn`.

## Theme 3: Risk Drivers → Risk Score card

**Extend:** `core/risk_score_flags.py` — add to existing `generate_risk_score_flags()`.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `top_recommendation` | recommendations list has entries | success | "{first recommendation text}" |
| `high_idiosyncratic` | idiosyncratic_variance_pct > 0.50 (from analysis_summary, 0-1 scale) | success | "{x*100:.0f}% of risk is stock-specific" |

**Data source:**
- `snapshot["recommendations"]` — plain text list, already on risk score snapshot (`risk.py:1999`). Use `recommendations[0]` as the message directly.
- `analysis_summary["idiosyncratic_variance_pct"]` — from `analysis_result.get_summary()`, already loaded in `_load_risk_score_flag_insights()`.

**Dropped from v1:** `top_risk_factor` with factor name + percentage — `risk_factors` are plain text, not structured factor-contribution records. The plain text entries aren't suitable for a clean insight. Can revisit if we add structured factor data to the snapshot.

**Wiring:** `top_recommendation` maps to `riskScore`. `high_idiosyncratic` also maps to `riskScore`. Need to pass `analysis_summary` to `generate_risk_score_flags()` as optional param (currently only receives the risk score snapshot).

## Theme 4: Risk-Adjusted Quality → Sharpe Ratio card

**Extend:** `core/performance_flags.py` — add to existing `generate_performance_flags()`.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `excellent_sharpe` | Sharpe >= 1.5 AND period >= 1yr | success | "Excellent risk-adjusted returns (Sharpe {x})" |
| `good_sharpe` | Sharpe >= 1.0 AND period >= 1yr | success | "Strong risk-adjusted returns (Sharpe {x})" |
| `sharpe_above_benchmark` | benchmark Sharpe available AND portfolio Sharpe - benchmark Sharpe > 0.2 | success | "Sharpe {x} vs benchmark {bm} — earning a premium for risk taken" |
| `sharpe_below_benchmark` | benchmark Sharpe available AND benchmark Sharpe - portfolio Sharpe > 0.2 | success | "Sharpe {x} vs benchmark {bm}" |
| `good_sortino` | Sortino > 1.5 AND period >= 1yr | success | "Sortino {x} — downside risk well managed" |

**Data source:** `snapshot["risk"]["sharpe_ratio"]`, `snapshot["risk"]["sortino_ratio"]`, `snapshot["benchmark"]["sharpe_ratio"]` (added in Step 0).

**Mapping:** Add to `_PERF_FLAG_MAP` → `sharpeRatio`.

**Note:** `low_sharpe` (existing, warning) will still win when Sharpe < 0.3. New flags fill the gap when Sharpe is decent/good.

## Theme 5: Benchmark Intelligence → Alpha Generation card

**Extend:** `core/alpha_flags.py` — add as additional context flags.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `asymmetric_capture` | up_capture > 1.0 AND down_capture < 1.0 | success | "Captures {up}x of gains, only {down}x of losses" |
| `unfavorable_capture` | up_capture < 1.0 AND down_capture > 1.0 | success | "Captures only {up}x of gains but {down}x of losses" |
| `high_tracking_error` | tracking_error > 10% | success | "High tracking error ({x}%) — portfolio diverges significantly from {benchmark}" |

**Data source:** `snapshot["risk"]["up_capture_ratio"]`, `snapshot["risk"]["down_capture_ratio"]`, `snapshot["risk"]["tracking_error_pct"]` (all added in Step 0).

These are **context flags** (severity: `success`). They supplement the primary alpha flag and surface as `marketContext`. When the primary alpha flag is `warning` or `info`, it wins in severity sort. When primary is `success` (e.g., `strong_alpha`), insertion order determines placement — the primary is appended first, so it stays as `aiInsight` and the context flag becomes `marketContext`.

**Note on capture ratios:** Only available when the snapshot has sufficient monthly data. Guard with None checks.

## Theme 6: Diversification Quality → Concentration card

**Extend:** `core/concentration_flags.py` — add as additional context flags.

| Flag | Trigger | Severity | Message |
|---|---|---|---|
| `factor_dominated` | factor_variance_pct > 0.70 (0-1 scale) | success | "{x*100:.0f}% of risk from market/sector factors — diversification reducing stock-specific risk" |
| `stock_specific_heavy` | idiosyncratic_variance_pct > 0.50 (0-1 scale) | success | "{x*100:.0f}% stock-specific risk — individual holdings drive outcomes" |

**Data source:** `analysis_summary["factor_variance_pct"]` and `analysis_summary["idiosyncratic_variance_pct"]` from `analysis_result.get_summary()`, already loaded in `_load_risk_score_flag_insights()`.

**Dropped from v1:** `many_sectors` — sector count isn't in `analysis_summary` and would need position data. Not worth the cross-loader plumbing for a simple "8 sectors" message.

**Wiring:** Extend `generate_concentration_flags()` to accept optional `analysis_summary: dict | None` param. Pass it from `_load_risk_score_flag_insights()`.

## Implementation Order

Group by touchpoint to reduce churn:

**Batch 1: Snapshot expansions** (Step 0)
- `core/result_objects/performance.py` — add 6 fields to `get_agent_snapshot()`
- `core/result_objects/realized_performance.py` — add 7 fields to `get_agent_snapshot()`
- Tests: verify new fields appear in snapshot output

**Batch 2: Performance flags** (Themes 2 + 4)
- `core/performance_flags.py` — add win rate, best/worst month, Sharpe quality, Sortino, benchmark Sharpe flags
- `mcp_tools/metric_insights.py` — add new flag types to `_PERF_FLAG_MAP`
- Tests: extend `tests/core/test_performance_flags.py`

**Batch 3: Alpha + Income flags** (Themes 5 + 1)
- `core/alpha_flags.py` — add capture ratio + tracking error context flags
- `core/income_insight_flags.py` — new file with income yield flags
- `mcp_tools/metric_insights.py` — add `_INCOME_FLAG_MAP`, wire income flags in alpha loader
- Tests: extend `tests/core/test_alpha_flags.py`, new `tests/core/test_income_insight_flags.py`

**Batch 4: Risk Score + Concentration flags** (Themes 3 + 6)
- `core/risk_score_flags.py` — add recommendation + idiosyncratic flags (needs `analysis_summary` param)
- `core/concentration_flags.py` — add factor/idiosyncratic split flags (needs `analysis_summary` param)
- `mcp_tools/metric_insights.py` — pass `analysis_summary` to both generators
- Tests: extend `tests/core/test_risk_score_flags.py`, `tests/core/test_concentration_flags.py`

## Files Changed

| File | Change |
|---|---|
| `core/result_objects/performance.py` | Expand `get_agent_snapshot()` — 6 new fields |
| `core/result_objects/realized_performance.py` | Expand `get_agent_snapshot()` — 7 new fields |
| `core/performance_flags.py` | Add win rate, best/worst month, Sharpe quality, Sortino, benchmark Sharpe flags |
| `core/alpha_flags.py` | Add capture ratio + tracking error context flags |
| `core/risk_score_flags.py` | Add recommendation + idiosyncratic flags, accept `analysis_summary` param |
| `core/concentration_flags.py` | Add factor/idiosyncratic split flags, accept `analysis_summary` param |
| `core/income_insight_flags.py` | **NEW** — income yield flags |
| `mcp_tools/metric_insights.py` | Add `_INCOME_FLAG_MAP`, wire income flags, pass `analysis_summary` to risk score + concentration generators |
| Tests (6 files) | Extend existing + 1 new test file for income flags |

## Risks / Notes

- **No new data fetches** — all data is already loaded by existing metric-insights loaders. Step 0 just exposes more fields from the same result objects.
- **Flag priority** — all new enrichment flags use `success` severity (lowest priority) except `harsh_worst_month` which is `warning`. This means existing `warning`/`error`/`info` flags always take `aiInsight`, and new flags land in `marketContext` or become `aiInsight` only when the portfolio is healthy. Some existing flags are also `success` (e.g., `strong_alpha`, `outperforming`, `excellent_risk`, `well_diversified`) — ties between `success` flags are resolved by insertion order (Python stable sort), which is deterministic since each generator appends flags in a fixed sequence and loaders merge in a fixed order.
- **Income flags only for realized mode** — hypothetical portfolios don't have income data. The income flag generator returns empty list when income fields are None. This is fine — the Total Portfolio Value card still has position flags (concentration, cash drag) as fallback.
- **`analysis_summary` threading** — both risk score and concentration generators need this param. It's already loaded in `_load_risk_score_flag_insights()` — just need to pass it through.
- **Capture ratios need guards** — can be None when insufficient monthly data. All new flags guard with None checks.
- **Dropped from v1:** `top_risk_factor` (risk_factors are plain text, not structured), `many_sectors` (sector count not in analysis_summary). Can revisit if we add structured data.
