# Metric Card Insights — Narrative Composers

## Context
The AI Insights on the 6 Overview metric cards currently echo the metric value back as a flag message ("Portfolio is down 0.8% total", "Max drawdown of 9.7% experienced"). The flag pipeline loads rich snapshots with full portfolio data — returns, risk metrics, benchmark comparisons, component scores — but the response builder (line 464) picks only `top["message"]`, discarding everything.

These are the first insights the investor sees. They should answer the "so what?" follow-up question.

## Codex Findings (Round 1 — all addressed)
1. **Fixed:** Raw data not on flags → pass raw snapshots from loaders to composers
2. **Fixed:** Global namespace collision → no flat extraction, typed snapshot dicts per composer
3. **Fixed:** Risk score composer → receives `risk_snapshot` + `analysis_summary` directly
4. **Fixed:** Threshold-gated fields → composers read from raw snapshot (always available)
5. **Fixed:** Fake drawdown/sigma math → removed
6. **Fixed:** YTD vs trailing 1Y → derive from `period.start_date`/`end_date`, not `mode`
7. **Fixed:** Cross-card coupling → each composer only reads its own data
8. **Fixed:** Confidence → simple completeness rule
9. **Fixed:** Other cards → legacy fallback
10. **Fixed:** Tests → update existing + add composer tests

## Codex Findings (Round 2 — all addressed)
11. **Fixed:** Builder iterates fixed `CARD_COMPOSERS.keys()`, not `insights.items()`. Cards with snapshots always get a composer call even with no flags — guarantees insights for normal portfolios
12. **Fixed:** Period label derived from `perf_snapshot["period"]["start_date"]`/`end_date`. If start is Jan 1 of current year → "YTD". Otherwise → "over the past N months"
13. **Fixed:** Risk snapshot field is `risk_category`, not `score_label`
14. **Fixed:** totalValue composer drops margin/leverage claims (those flags map to dayChange). Sticks to concentration + top-5 + income yield

## Codex Findings (Round 3 — all addressed)
15. **Fixed:** Initialize `perf_snapshot = {}`, `risk_snapshot = {}`, `analysis_summary = {}` at the top of `build_metric_insights()` before the futures/error branches. Loaders overwrite on success. Composers receive `{}` on failure → graceful degradation
16. **Fixed:** Don't pop — use `insights.get(card_id, [])` instead. If composer returns empty/None, fall through to the flag-based fallback in the second loop. Changed from pop to get.
17. **Fixed:** Removed stale "use snapshot mode" from design principles. Period label derived from `period.start_date`/`end_date` only

## Codex Findings (Round 4 — all addressed)
18. **Fixed:** riskScore verdict fallback — the generic fallback loop checks `if card_id == "riskScore"` and uses `risk_snapshot.get("verdict", "")` as marketContext (same as current behavior). This preserves the verdict even when the composer returns empty

## Codex Findings (Round 5 — all addressed)
19. **Accepted:** totalValue remains conditional — it reads from position flags which are threshold-gated. For a healthy diversified portfolio with no concentration issues, no insight is shown (the number speaks for itself). This is correct behavior, not a bug. The flag-based fallback handles it when there IS something to say. totalValue composer is a best-effort formatter of existing flags, not a snapshot-backed guaranteed insight

## Approach
The two loader functions (`_load_risk_score_flag_insights` and `_load_alpha_flag_insights`) already load full snapshots:
- `_load_alpha_flag_insights` has the performance `snapshot` (line 280/301) — contains `returns`, `risk`, `benchmark`, `period`
- `_load_risk_score_flag_insights` has `risk_snapshot` (line 214) + `analysis_summary` (line 212) — contains component scores, violations, verdict

**Change the loaders to also return these raw snapshots.** The response builder receives them alongside the flags and passes them to per-card composers.

## Plan

**File:** `mcp_tools/metric_insights.py`

### Change 1: Return raw snapshots from loaders

**`_load_risk_score_flag_insights()`** — currently returns `dict[str, list[dict]]` (flags only).
Change return to `tuple[dict[str, list[dict]], dict, dict]` — `(flags, risk_snapshot, analysis_summary)`.

**`_load_alpha_flag_insights()`** — currently returns `dict[str, list[dict]]` (flags only).
Change return to `tuple[dict[str, list[dict]], dict]` — `(flags, perf_snapshot)`.

Update the callers in `build_metric_insights()` (lines 421-445) to unpack the tuples:
```python
# Risk
risk_payload = risk_future.result()
risk_flags, risk_snapshot, analysis_summary = risk_payload["result"]
# ...merge flags...

# Alpha/perf
alpha_payload = alpha_future.result()
alpha_flags, perf_snapshot = alpha_payload["result"]
# ...merge flags...
```

Position flags don't need snapshots — their insights are already well-served by flag data (ticker names, weights are on the flags).

### Change 2: Six narrative composer functions

Each composer takes specific snapshot data and the flags for that card. Returns `{"aiInsight": str, "aiConfidence": int, "marketContext": str}`.

**`_compose_total_value(flags)`** — reads from position flags directly (they carry ticker, weight_pct, top5_weight_pct)
- Primary: top concentration insight (ticker + weight)
- Context: top-5 concentration or income yield if available
- Example: "DSU at 28.6% is your largest position. Top 5 holdings are 68% of total exposure."

**`_compose_ytd_return(flags, perf_snapshot)`** — reads from `perf_snapshot["returns"]` + `perf_snapshot["mode"]`
- Reads: `total_return_pct`, `win_rate_pct`, `best_month_pct`, `best_month_date`, `worst_month_pct`, `worst_month_date`, `period.start_date`/`end_date`
- Primary: direction + win rate. Derives period label from dates (if start is Jan 1 current year → "YTD", else "over the past N months")
- Context: best/worst month with dates
- Example: "Down 0.8% over the past year. Positive 58% of months. Best: +4.2% (Dec 2025), worst: -3.1% (Oct 2024)."

**`_compose_max_drawdown(flags, perf_snapshot)`** — reads from `perf_snapshot["risk"]`
- Reads: `max_drawdown_pct`, `volatility_pct`
- Primary: drawdown severity label (Minimal/Moderate/Significant/Severe)
- Context: relative to portfolio's own volatility level (descriptive, not fake math)
- Example: "Worst decline of 9.7% from peak. Portfolio runs at 8.4% annual volatility — this drawdown is moderate for the risk profile."

**`_compose_risk_score(flags, risk_snapshot, analysis_summary)`** — reads from `risk_snapshot`
- Reads: `overall_score`, `risk_category`, `component_scores` (dict with volatility_risk, concentration_risk, etc.), `verdict`, `violation_count`
- Primary: strongest + weakest component
- Context: what's driving the weakness (concentration driver from risk_snapshot) + verdict
- Example: "Strongest: volatility 100/100, factor risk 100/100. Weakest: concentration 81/100 — driven by single-stock exposure."

**`_compose_sharpe(flags, perf_snapshot)`** — reads from `perf_snapshot["risk"]` + `perf_snapshot["benchmark"]`
- Reads: `sharpe_ratio`, `benchmark.sharpe_ratio`, `sortino_ratio`
- Primary: vs benchmark comparison
- Context: sortino for downside perspective
- Example: "Sharpe -0.26 vs SPY's 1.03. Negative means earning less than T-bills for the volatility taken. Sortino -0.18."

**`_compose_alpha(flags, perf_snapshot)`** — reads from `perf_snapshot["benchmark"]` + `perf_snapshot["risk"]`
- Reads: `alpha_annual_pct`, `up_capture_ratio`, `down_capture_ratio`, `tracking_error_pct`, `beta`, `ticker`
- Primary: alpha direction + capture ratio story
- Context: beta + tracking error
- Example: "Trailing SPY by 7.9% annualized. Down capture 85% vs up capture 62% — absorbing most losses but missing gains."

### Change 3: Replace the response builder (lines 447-474)

```python
CARD_COMPOSERS = {
    "totalValue": lambda flags, **kw: _compose_total_value(flags),
    "ytdReturn": lambda flags, **kw: _compose_ytd_return(flags, kw.get("perf_snapshot", {})),
    "maxDrawdown": lambda flags, **kw: _compose_max_drawdown(flags, kw.get("perf_snapshot", {})),
    "riskScore": lambda flags, **kw: _compose_risk_score(flags, kw.get("risk_snapshot", {}), kw.get("analysis_summary", {})),
    "sharpeRatio": lambda flags, **kw: _compose_sharpe(flags, kw.get("perf_snapshot", {})),
    "alphaGeneration": lambda flags, **kw: _compose_alpha(flags, kw.get("perf_snapshot", {})),
}

with timing.step("build_response"):
    verdict_list = insights.pop("_riskScore_verdict", [])
    if risk_snapshot:
        risk_snapshot["verdict"] = verdict_list[0].get("message", "") if verdict_list else ""

    result: dict[str, dict] = {}

    # 1. Try snapshot-backed composers for hero cards (fixed set)
    composed_cards: set[str] = set()
    for card_id, composer in CARD_COMPOSERS.items():
        flags = insights.get(card_id, [])
        composed = composer(
            flags,
            perf_snapshot=perf_snapshot,
            risk_snapshot=risk_snapshot,
            analysis_summary=analysis_summary,
        )
        if composed and composed.get("aiInsight"):
            result[card_id] = composed
            composed_cards.add(card_id)

    # 2. Flag-based fallback for ALL cards not handled by composers
    #    (including hero cards where composer returned empty)
    for card_id, flags in insights.items():
        if card_id in composed_cards or not flags or card_id.startswith("_"):
            continue
        sorted_flags = sorted(flags, key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "info"), 9))
        top = sorted_flags[0]
        # Preserve riskScore verdict fallback (matches current behavior)
        fallback_context = ""
        if len(sorted_flags) > 1:
            fallback_context = sorted_flags[1]["message"]
        elif card_id == _RISK_SCORE_CARD:
            fallback_context = risk_snapshot.get("verdict", "")

        result[card_id] = {
            "aiInsight": top["message"],
            "aiConfidence": _SEVERITY_CONFIDENCE.get(top.get("severity", "info"), 60),
            "marketContext": fallback_context,
        }

    return result
```

### Composer Design Principles

1. **Never restate the number** — the card already shows it
2. **Read from snapshots, not flags** — snapshots always have the data; flags are threshold-gated
3. **Graceful degradation** — if a snapshot field is None, omit that part. Build what you can.
4. **Confidence based on data completeness**: count key fields present / total key fields. Approximate: >=80% → 85, >=50% → 70, else 55
5. **Label the time window** — derive from `period.start_date`/`end_date` (Jan 1 of current year → "YTD", else "over the past N months")
6. **Concrete** — name tickers, give percentages

### Error handling

- If a loader fails (raises exception), its snapshot is `{}` and its flags are `[]`
- Composers receive `{}` snapshot → graceful degradation, minimal insight or empty
- If ALL loaders fail, the endpoint returns `{"success": true, "insights": {}, "total": 0}`
- Legacy fallback cards (dayChange, etc.) still use flag-based messages

## Files Modified
1. `mcp_tools/metric_insights.py` — change loader returns, add 6 composers, replace response builder
2. `tests/mcp_tools/test_metric_insights.py` — update existing assertions + add composer tests

## Verification
1. `pytest tests/mcp_tools/test_metric_insights.py -v` — all tests pass
2. Restart backend, reload Overview, toggle AI Insights
3. Each card shows a narrative insight answering "so what?"
4. Insights use real numbers from the portfolio (not generic text)
5. Cards with no perf/risk data gracefully show minimal or no insight
6. Legacy cards (dayChange, volatilityAnnual, concentration) still work via fallback
