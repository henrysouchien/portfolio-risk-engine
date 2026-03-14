# Portfolio-MCP Agent-Friendliness Audit

_Created: 2026-02-24_
_Updated: 2026-02-25 — Phase 3 complete. 14 tools have agent format._
_Status: **COMPLETE**_

## Purpose

Systematic review of every portfolio-mcp tool asking: **is this output designed for an agent to reason with?** The `get_risk_analysis(format="agent")` redesign established the pattern. This audit applies the same lens to all 20 tools.

## Evaluation Criteria

For each tool, we evaluate:

1. **Response size** — Does it fit in agent context, or does it blow up the window?
2. **Decision-oriented** — Does it answer "what should I do?" or just "here's some data"?
3. **Flags/signals** — Does it surface things that need attention?
4. **Structure** — Are there clear buckets the agent can reason over?
5. **Defaults** — Does the default format work well for agents?
6. **Description** — Is the tool description clear enough for an agent to know when to use it?

### Scoring

- **A** — Agent-ready. Structured for reasoning, right-sized, has flags/signals.
- **B** — Functional but not optimized. Returns useful data, but agent has to do interpretation work.
- **C** — Raw data dump. Agent gets flooded or has to parse unstructured output.
- **N/A** — Action tool (trading, config) — correctness matters more than reasoning structure.

---

## Tool-by-Tool Audit

### 1. `get_positions` — Grade: **A** ~~B~~ (agent format implemented)

**What it does:** Fetch portfolio positions from brokerage accounts.

**Formats:** full, summary, list, by_account, monitor, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `PositionResult.get_top_holdings()` + `get_exposure_snapshot()` → `core/position_flags.py` (concentration, leverage, margin, cash drag, stale data, diversification) → thin MCP composition. `output="file"` saves full payload to disk. Snapshot separates `cash_balance` vs `margin_debt`, `short_exposure` vs margin, adds `investable_count`.

See: `docs/planning/POSITIONS_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 2. `get_risk_score` — Grade: **A** ~~B+~~ (agent format implemented)

**What it does:** 0-100 risk score with compliance status.

**What agent gets (summary):**
```json
{
  "status": "success",
  "overall_score": 42,
  "risk_category": "Moderate",
  "component_scores": {...},
  "is_compliant": true,
  "total_violations": 0,
  "recommendations": [...top 5],
  "risk_factors": [...top 5]
}
```

**What's good:**
- Already has `is_compliant` boolean — instant pass/fail
- `recommendations` are actionable strings
- `risk_factors` surface what's driving the score
- Right-sized (~1-2KB)

**Issues:**
- No severity on recommendations (all look equal)
- No delta from previous score (was it 42 last time or 65?)
- `component_scores` is raw sub-scores without interpretation

**Agent format should add:**
- Severity on recommendations (high/medium/low)
- One-line verdict: "Portfolio risk is moderate and compliant" or "Portfolio risk is elevated — 2 violations"
- Optional: score trend if historical scores are available

**Priority: LOW** — Already quite agent-friendly. Minor polish.

---

### 3. `get_risk_analysis` — Grade: **A** (already has `format="agent"`)

**What it does:** Comprehensive risk analytics (volatility, factors, compliance, etc.)

**Already implemented:**
- `format="agent"` with structured buckets (snapshot, flags, compliance, risk_attribution, factor_exposures, industry_concentration, variance_decomposition)
- `output="file"` for full data dump to disk
- Flags layer with severity (error/warning/info)

**No changes needed** — this is the reference implementation.

---

### 4. `get_performance` — Grade: **A** ~~C+~~ (agent format implemented)

**What it does:** Portfolio performance metrics and benchmark comparison.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on both `PerformanceResult` and `RealizedPerformanceResult` → `core/performance_flags.py` (12 flags: negative return, benchmark underperformance, low Sharpe, deep drawdown, high volatility, data coverage, data quality, synthetic positions, NAV estimated, high confidence, outperforming) → thin MCP composition. Also fixed pre-existing `_categorize_performance()` bug. 10 Codex review rounds, 43 new tests.

See: `docs/planning/PERFORMANCE_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 5. `get_trading_analysis` — Grade: **A** ~~C~~ (agent format implemented)

**What it does:** Trading quality and behavior metrics from transaction history.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on `TradingAnalysisResult` → `core/trading_flags.py` (flags for turnover, win rate, round-trips, timing) → thin MCP composition. `output="file"` saves full trade list to disk. Snapshot includes key trading quality metrics without the full trade history.

**Priority: DONE**

---

### 6. `analyze_stock` — Grade: **A** ~~B~~ (agent format implemented)

**What it does:** Single-stock risk/factor analysis.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on `StockAnalysisResult` → `core/stock_flags.py` (flags for high beta, high volatility, low R-squared, rate sensitivity, idiosyncratic risk) → thin MCP composition. `output="file"` saves full analysis to disk. Snapshot includes risk characterization and factor exposures.

**Priority: DONE**

---

### 7. `run_optimization` — Grade: **A** ~~B-~~ (agent format implemented)

**What it does:** Optimize portfolio weights (min variance or max return).

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on `PortfolioOptimizationResult` → `core/optimization_flags.py` (flags for marginal improvement, large rebalance, concentration risk, constraint binding) → thin MCP composition. `output="file"` saves full optimization to disk. Snapshot includes before/after risk metrics, top weight changes, and trade count. 51 new tests.

See: `docs/planning/OPTIMIZATION_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 8. `run_whatif` — Grade: **A** ~~B-~~ (agent format implemented)

**What it does:** Evaluate risk impact of proposed allocation changes.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on `WhatIfResult` → `core/whatif_flags.py` (flags for risk improvement/deterioration, new compliance violations, concentration changes) → thin MCP composition. `output="file"` saves full what-if to disk. Snapshot includes before/after risk metrics, compliance delta, and top weight changes. 64 new tests.

See: `docs/planning/WHATIF_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 9. `check_exit_signals` — Grade: **A** ~~A-~~ (agent format implemented)

**What it does:** Evaluate exit signals for a position.

**What agent gets (summary):**
```json
{
  "status": "success",
  "ticker": "SLV",
  "overall_assessment": "EXIT — primary momentum signal triggered",
  "signals": [...each rule with triggered/severity],
  "position": {...shares, cost_basis, value},
  "recommended_actions": [
    {"step": 1, "action": "SELL", "ticker": "SLV", "quantity": 75, "reasoning": "..."},
    {"step": 2, "action": "PLACE_STOP", ...}
  ],
  "trade_eligible": true
}
```

**What's good:**
- `overall_assessment` is a clear verdict
- `recommended_actions` are structured and actionable (agent can chain to `preview_trade`)
- Per-signal `triggered` + `severity` is clean
- `trade_eligible` is a clear go/no-go

**Issues:**
- Only works for pre-configured tickers (currently just SLV)
- Config is hardcoded in the source file, not dynamic
- No "since last check" delta

**Agent format changes:** Minimal — already well-designed. Consider:
- Return empty config list for unconfigured tickers instead of error (agent can still decide)
- Historical trend context if available

**Priority: LOW** — Already agent-friendly.

---

### 10. `suggest_tax_loss_harvest` — Grade: **A** ~~B+~~ (agent format implemented)

**What it does:** Identify tax-loss harvesting opportunities from FIFO lots.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `_build_tax_harvest_snapshot()` (standalone, consolidates lots by ticker → top 5) → `core/tax_harvest_flags.py` (wash_sale_risk, significant_harvest ≥$3K, low/moderate coverage, mostly_short_term) → thin MCP composition. Key innovation: ticker consolidation reduces 79 individual lots to 5 ticker summaries (84KB → ~1KB). `output="file"` saves full lot-level payload to disk.

See: `docs/planning/TAX_HARVEST_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 11. `get_factor_analysis` — Grade: **A** ~~B-~~ (agent format implemented)

**What it does:** Factor correlations, performance, and returns analysis.

**Formats:** full, summary, report, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `get_agent_snapshot()` on all 3 result types (`FactorCorrelationResult`, `FactorPerformanceResult`, `FactorReturnsResult`) → `core/factor_flags.py` (dispatches by `analysis_type`: correlation pair flags, Sharpe-based performance flags, extreme return flags, insufficient data detection) → thin MCP composition. Each mode produces a tailored snapshot: correlations surfaces high-correlation pairs (upper triangle, symmetric assumption) + overlays; performance ranks by Sharpe with macro composites + verdict; returns shows top/bottom per window with dynamic ytd mapping. `output="file"` saves full payload to disk. 21 Codex review rounds (most complex of the 7), 90 new tests.

See: `docs/planning/FACTOR_ANALYSIS_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 12. `get_factor_recommendations` — Grade: **A** ~~B~~ (agent format implemented)

**What it does:** Factor-based hedge/offset recommendations.

**What agent gets (summary, single mode):**
```json
{
  "status": "success",
  "mode": "single",
  "overexposed_factor": "Real Estate",
  "recommendations": [{...}, ...],
  "recommendation_count": 5
}
```

**What's good:**
- Already recommendation-oriented (not raw data)
- Portfolio mode identifies risk drivers automatically

**Issues:**
- No implementation difficulty/cost signal (is the hedge expensive? liquid?)
- No expected impact ("adding X would reduce real estate exposure by Y%")
- Recommendations list can be long without prioritization

**Agent format should add:**
- Top 1-2 recommended actions with expected impact
- Flag if no good hedges exist
- Cost/liquidity context if available

**Priority: LOW**

---

### 13. `get_income_projection` — Grade: **A** ~~B+~~ (agent format implemented)

**What it does:** Project portfolio dividend income.

**What agent gets (summary):**
```json
{
  "status": "success",
  "total_projected_annual_income": 4250.00,
  "portfolio_yield_on_value": 2.6,
  "portfolio_yield_on_cost": 3.1,
  "next_3_months": {...per month totals},
  "top_5_contributors": [...],
  "upcoming_dividends": [...next 3],
  "warnings": [...]
}
```

**What's good:**
- Top-line income number is immediately useful
- Yield on cost and yield on value
- Upcoming dividends (actionable near-term view)
- Warnings for variable/recently-initiated dividends

**Issues:**
- No benchmark comparison ("your yield is above/below average for this risk profile")
- No income trend (growing, flat, declining)
- No concentration flag ("60% of income comes from 2 positions")

**Agent format should add:**
- Income concentration flag (single-name risk to income stream)
- Growth trend if historical data available
- "Calendar" highlights (big payment months)

**Priority: LOW** — Already pretty good.

---

### 14-17. Trading Tools (`preview_trade`, `execute_trade`, `get_orders`, `cancel_order`) — Grade: **N/A**

These are action tools. Their contract is correctness, not analysis.

**`preview_trade`** returns a `TradePreviewResult` — should include:
- Clear go/no-go (`can_execute: true/false`)
- Risk impact preview (how does this change portfolio risk?)
- Compliance check (would this trigger violations?)
- Cost estimate

**`execute_trade`** — returns execution status. Fine as-is.

**`get_orders`** — summary mode has `status_counts` which is good. Could add flags for failed/rejected orders.

**`cancel_order`** — returns status. Fine as-is.

**Priority: LOW** — Action tools, correctness > format.

---

### 18. `get_leverage_capacity` — Grade: **A** ~~B~~ (agent format implemented)

**What it does:** Compute leverage headroom before hitting risk limits.

**Formats:** full, **agent**

**Agent format (`format="agent"`):**
Three-layer architecture: `_build_leverage_snapshot()` (standalone, extracts breached/tightest constraints, invariant failures, core warnings) → `core/leverage_capacity_flags.py` (over_leveraged, multiple_breaches, tight_headroom <10%, invariant_breach, capacity_warnings) → thin MCP composition. Verdict identifies binding constraint and headroom percentage. `output="file"` saves full capacity payload to disk.

See: `docs/planning/LEVERAGE_CAPACITY_AGENT_FORMAT_PLAN.md`

**Priority: DONE**

---

### 19-20. Risk Profile Tools (`set_risk_profile`, `get_risk_profile`) — Grade: **B+**

These are config tools. `set_risk_profile` returns applied limits + changes — good for agent to confirm what was set. `get_risk_profile` returns current state — good.

**Minor improvements:**
- `set_risk_profile` could include a 1-line summary: "Set income profile with 25% max loss, 12% vol target"
- `get_risk_profile` could include a verdict about current limits vs actual portfolio risk

**Priority: LOW**

---

### 21. `get_portfolio_news` / `get_portfolio_events_calendar` — Grade: **B**

These are pass-through wrappers to fmp-mcp with portfolio symbol auto-fill.

**What's good:**
- Auto-fills portfolio symbols — agent doesn't need to enumerate tickers
- `auto_filled_from_portfolio: true` flag

**Issues:**
- Delegates formatting entirely to underlying fmp-mcp tools
- No portfolio-context enrichment ("this earnings report is for your largest position")

**Priority: LOW** — Mostly a convenience wrapper.

---

### 22. `analyze_option_strategy` — Grade: **A** ~~B-~~ (agent format implemented)

**What it does:** Options strategy P&L and Greeks analysis.

**What agent gets (summary):** Calls `result.to_summary()` — shape unknown.

**Issues:**
- Need to verify what `OptionAnalysisResult.to_summary()` returns
- Should include clear verdict: "Max profit: $X, max loss: $Y, breakeven at $Z"
- Should flag if strategy is undefined risk (naked short, etc.)
- No portfolio context (how does this option position affect overall portfolio risk?)

**Priority: LOW** — Specialized tool, relatively new.

---

## Priority Summary

| Priority | Tools | Status |
|----------|-------|--------|
| **HIGH** | `get_positions`, `get_performance` | **DONE** — agent format implemented |
| **MEDIUM** | `get_trading_analysis`, `analyze_stock`, `run_optimization`, `run_whatif`, `get_factor_analysis` | **DONE** — agent format implemented |
| **LOW** | `get_risk_score`, `get_factor_recommendations`, `analyze_option_strategy`, `check_exit_signals`, `get_income_projection`, `suggest_tax_loss_harvest`, `get_leverage_capacity` | **DONE** — agent format implemented |
| **Skip** | Trading tools, config tools, news/events pass-throughs | N/A or already adequate |
| **Reference** | `get_risk_analysis` | **DONE** — original reference implementation |

---

## Implementation Strategy

### Pattern: `format="agent"` everywhere

Apply the same pattern established in `get_risk_analysis`:

1. **Add `format="agent"` to each tool** — structured, right-sized, decision-oriented
2. **Each agent format has a `flags` list** — severity-tagged signals
3. **Each agent format has a 1-line `verdict`** — the TL;DR
4. **`output="file"` where appropriate** — full data on disk, agent gets summary

### Shared infrastructure

- **`core/risk_flags.py`** already exists — extend or create parallel modules
- **`_generate_flags()` pattern** — separate interpretive logic from data accessors
- **Verdict generation** — simple rules that produce 1-2 sentence summaries

### Implementation order

1. **`get_positions`** + **`get_performance`** — highest impact, most called
2. **`run_whatif`** + **`analyze_stock`** — support the trade decision workflow
3. **`get_trading_analysis`** + **`run_optimization`** + **`get_factor_analysis`** — analysis depth
4. Everything else — polish pass

### Cross-cutting: Default format

Today most tools default to `format="summary"`. For an agent-first design, consider:
- Change default to `format="agent"` when called via MCP? (breaking change, needs thought)
- Or: keep `summary` default, make `agent` the recommended format in tool descriptions
- Or: detect caller context (MCP vs API) and auto-select format

**Recommendation:** Keep `summary` as default for backward compatibility. Update tool descriptions to recommend `format="agent"` for AI assistants. Let the agent learn to use it.

---

## Completion Log

All 7 HIGH+MEDIUM priority tools now have `format="agent"` + `output="file"`:

| Tool | Tests | Review Rounds | Commit |
|------|-------|--------------|--------|
| `get_positions` | ~30 | 4 | (2026-02-24) |
| `get_performance` | 43 | 10 | (2026-02-24) |
| `get_trading_analysis` | ~25 | — | (2026-02-24) |
| `analyze_stock` | ~20 | — | (2026-02-24) |
| `run_optimization` | 51 | 7 | (2026-02-25) |
| `run_whatif` | 64 | 5 | (2026-02-25) |
| `get_factor_analysis` | 90 | 21 | (2026-02-25, `e3cda57b`) |

All 7 tools live-tested against real portfolio data on 2026-02-25.

### Phase 2: Remaining LOW-priority tools (2026-02-25)

| Tool | Tests | Review Rounds | Commit |
|------|-------|--------------|--------|
| `get_risk_score` | 24 | 2 (R1 FAIL, R2 PASS) | `bfb9061c` |
| `get_factor_recommendations` | 29 | 3 (R1 FAIL, R2 FAIL, R3 PASS) | `d2c9ccf1` |
| `analyze_option_strategy` | 33 | 3 (R1 FAIL, R2 FAIL, R3 PASS) | `d2c9ccf1` |
| `check_exit_signals` | 22 | 1 (R1 PASS) | `d2c9ccf1` |
| `get_income_projection` | 31 | 2 (R1 FAIL, R2 PASS) | `d2c9ccf1` |

All 5 tools live-tested against real portfolio data on 2026-02-25. File output (`output="file"`) verified for risk_score, exit_signals, and income_projection.

**Phase 2 total: 139 new tests across 5 tools.**

### Phase 3: Additional tools from live testing review (2026-02-25)

Live-tested 5 "skipped" tools to assess need. `suggest_tax_loss_harvest` (84KB summary output) and `get_leverage_capacity` (actionable over-leveraged flags) warranted agent format. The other 3 (`get_risk_profile`, `get_portfolio_news`, `get_portfolio_events_calendar`) confirmed as skip — config/pass-through tools.

| Tool | Tests | Review Rounds | Commit |
|------|-------|--------------|--------|
| `suggest_tax_loss_harvest` | 34 | 2 (R1 FAIL, R2 PASS) | pending |
| `get_leverage_capacity` | 27 | 2 (R1 FAIL, R2 PASS) | pending |

Both tools live-tested against real portfolio data on 2026-02-25. File output verified for both.

**Grand total: 14 tools with agent format, ~600 new tests across all phases.**

## Next Steps

1. [x] ~~Review this audit — align on priorities and approach~~
2. [x] ~~Implement `format="agent"` for `get_positions`~~
3. [x] ~~Implement `format="agent"` for `get_performance`~~
4. [x] ~~Implement for remaining HIGH/MEDIUM tools~~
5. [x] ~~Update tool descriptions to recommend `format="agent"` for AI callers~~
6. [x] ~~Update `docs/interfaces/mcp.md` with agent format documentation~~
7. [x] ~~Fix `annual_return_pct` double-scaling bug in factor performance~~ (commit `af45db96`)
8. [x] ~~Phase 2 — Remaining tools:~~
   - [x] `get_risk_score` (B+ → A) — 24 tests
   - [x] `get_factor_recommendations` (B → A) — 29 tests
   - [x] `analyze_option_strategy` (B- → A) — 33 tests
   - [x] `check_exit_signals` (A- → A) — 22 tests
   - [x] `get_income_projection` (B+ → A) — 31 tests
9. [x] ~~Phase 3 — Additional tools from live testing:~~
   - [x] `suggest_tax_loss_harvest` (B+ → A) — 34 tests, ticker consolidation (84KB → 1KB)
   - [x] `get_leverage_capacity` (B → A) — 27 tests, over-leveraged detection
   - Skip: `set/get_risk_profile` (B+ — config tools, already compact)
   - Skip: `get_portfolio_news/events` (B — pass-through wrappers, no interpretation needed)
