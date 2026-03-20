# Improve Performance Insights Quality

## Context
The Performance view's "AI Insights" section (toggled via lightbulb button) shows 3 insight cards: Performance, Risk, Opportunity. The current `_generate_structured_insights()` in `PerformanceResult` produces shallow, generic text — it only references alpha, vol/drawdown/beta, and Sharpe. The object has much richer data (sector attribution, security attribution, win rate, sortino, benchmark comparison with benchmark Sharpe/vol, information ratio) that isn't being leveraged. The `action` field exists in the data but isn't rendered on the frontend.

## Files to Modify

### 1. `core/result_objects/performance.py` — Rewrite `_generate_structured_insights()` (lines 401-489)

Add two private helpers, then rewrite the method body. Return shape is unchanged: `Dict[str, Dict[str, str]]` with keys performance/risk/opportunity, each having text/action/impact.

**New helpers:**

```python
def _top_sector_contributor(self) -> tuple:
    """Return (name, contribution%) for the top POSITIVE sector contributor."""
    # Filter to contribution > 0, exclude name == "Unknown", pick max.
    # Guarded for None, empty list, or all-negative sectors → (None, None).

def _top_security_detractor(self) -> tuple:
    """Return (name, contribution%) for worst security detractor."""
    # Filter to contribution < 0, exclude name == "Unknown", pick min.
    # Guarded for None, empty list, or no negatives → (None, None).
```

**Performance card** — enriched with:
- Alpha direction (existing)
- Top positive sector contributor name + contribution % (from `self.sector_attribution`, excluding "Unknown" rows)
- Win rate + period length (from `self.returns.win_rate`, `self.analysis_period.total_months`)
- Action references top detractor when alpha < 0

Example: "Portfolio generated 2.1% alpha, driven by Technology (+3.2%). Win rate of 72% across 18 months shows consistent execution."

**Risk card** — enriched with:
- Vol ratio vs benchmark (portfolio vol / `self.benchmark_comparison.benchmark_volatility`) — only when benchmark_volatility > 0
- Max drawdown (existing)
- Sortino assessment (from `self.risk_adjusted_returns.sortino_ratio`)
- Beta only when notable (>1.1 or <0.9)

Example: "Portfolio vol of 15.2% is 0.8x the benchmark (18.9%), max drawdown -12.1%. Sortino of 1.8 shows strong downside management."

**Opportunity card** — enriched with:
- Sharpe vs benchmark Sharpe (from `self.benchmark_comparison.benchmark_sharpe`) — only when benchmark_sharpe > 0
- Top detractor name + drag (from `self.security_attribution`, excluding "Unknown")
- Information ratio when available

Example: "Sharpe of 0.85 trails the benchmark's 1.12. Top detractor TSLA (-2.1% drag) offers the most room for improvement."

**Impact thresholds** — same as current, with one addition: override opportunity to "high" if benchmark_sharpe > 0 and portfolio Sharpe < 70% of benchmark Sharpe.

**Graceful degradation** — every new data reference is guarded for None, empty list `[]`, zero/negative denominators, and "Unknown" sector names. When attribution data is unavailable or meaningless, insight degrades to current-quality simple text. No crashes.

### 2. `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx` — Render `action` field

After the insight `text` paragraph (line 243), add:
```tsx
{insight.action ? (
  <p className="mt-2 text-xs font-medium text-muted-foreground">
    <Target className="mr-1 inline h-3 w-3" />
    {insight.action}
  </p>
) : null}
```
`Target` icon is already imported (line 13). `InsightCard` type already has `action: string`. No type changes needed.

### 3. `tests/core/test_structured_insights.py` — New test file (~12 tests)

Test the rewritten method with various data combinations:
- With/without sector_attribution → text mentions/omits sector
- With/without security_attribution → action mentions/omits detractor
- Win rate + period length in performance text
- Vol ratio vs benchmark in risk text
- Sortino strong/weak in risk text
- Sharpe vs benchmark Sharpe in opportunity text
- All-None attribution → graceful fallback
- Return shape unchanged (3 keys, each with text/action/impact strings)
- Impact threshold correctness

Use a local factory in the test file (based on the pattern in `tests/core/test_performance_flags.py`, not cross-module imports).

## Verification
1. `python -m pytest tests/core/test_structured_insights.py -v`
2. `python -m pytest tests/mcp_tools/test_performance_agent_format.py -v` (regression)
3. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json`
4. Open Chrome → Performance tab → toggle lightbulb → confirm richer insight text with action line
