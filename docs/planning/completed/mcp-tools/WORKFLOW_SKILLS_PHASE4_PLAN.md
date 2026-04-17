# Workflow Skills Phase 4 — Hedging, Scenario Analysis, Strategy Design

**Status**: COMPLETE — part of \"All 7 workflows complete\" (tracked in `completed/TODO_COMPLETED.md`, 2026-03-01)

## Context

Phase 2 delivered allocation-review and risk-review skills (2 of 7 workflows). Phase 4 adds the next 3: Hedging, Scenario Analysis, and Strategy Design. Stock Research deferred (needs integration with existing deep-dive research process). Performance Review already exists as a skill.

Same pattern as Phase 2: markdown choreography files in AI-excel-addin that chain existing MCP tools into structured workflows. No backend changes needed — `hedging`, `scenario_analysis`, `strategy_design` are already in `_ALLOWED_WORKFLOWS` (audit.py line 13).

Key difference from WORKFLOW_DESIGN.md: two major gaps have been **closed** since the design was written:
- `compare_scenarios()` now exists — batch what-if and optimization comparison with ranking
- `preview_rebalance_trades()` now exists — target weights → sequenced BUY/SELL legs

---

## Changes

### 1. `hedging.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/hedging.md`

7-step workflow: scope → assess → diagnose exposures → find candidates → model → compare scenarios → execute.

Key tool chain:
- Step 2: `get_risk_analysis` + `get_risk_score` + `get_factor_analysis(analysis_type="correlations")` + `get_positions` + `get_action_history(workflow_filter="hedging")` (all parallel)
- Step 4: `get_factor_recommendations(mode="portfolio")`, optionally `analyze_option_chain(symbol="...", expiry="YYYYMMDD")`, `get_futures_curve(symbol="...")`, `list_baskets`
- Step 5: `analyze_option_strategy(legs="[{...}]")` for options (JSON string), sizing math for ETF/futures
- Step 6: `compare_scenarios(mode="whatif", scenarios="[...]", rank_by="vol_delta", rank_order="asc")` for batch comparison (scenarios is a JSON string)
- Step 7: `preview_trade(ticker="...", quantity=N, side="BUY"|"SELL", account_id="...")` → `execute_trade(preview_id=...)`

Audit: `record_workflow_action(workflow_name="hedging", recommendation_type="hedge", recommendation_text="...", source_tool="compare_scenarios")` at step 6.

Breakpoints: after step 3 (exposure diagnosis), after step 6 (scenario comparison).

### 2. `scenario-analysis.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/scenario-analysis.md`

5-step workflow: define scenario → run analysis → compare outcomes → refine → execute.

Three input modes:
- Custom: user provides `target_weights` or `delta_changes`
- Template: user describes a theme, agent constructs the weights
- Stress test: user describes a market condition, agent constructs position changes

Key tool chain:
- Step 1: `get_positions` + `get_risk_analysis` + `get_action_history(workflow_filter="scenario_analysis")` (parallel)
- Step 2: `run_whatif(delta_changes={...}, format="agent")` — single scenario
- Step 3: `compare_scenarios(mode="whatif", scenarios="[...]", rank_by="vol_delta", rank_order="asc")` — batch (scenarios is a JSON string)
- Step 4: `run_whatif` (tweaked) or `run_optimization`
- Step 5: `preview_rebalance_trades` → `preview_trade` → `execute_trade(preview_id=...)`

Audit: `record_workflow_action(workflow_name="scenario_analysis", recommendation_type="rebalance", recommendation_text="...", source_tool="compare_scenarios")` at step 3.

Breakpoints: after step 2 (single scenario results), after step 3 (comparison).

### 3. `strategy-design.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/strategy-design.md`

5-step workflow: set objectives → optimize → compare variants → validate & save → execute.

Two entry points: build new vs improve existing.

Key tool chain:
- Step 1: `get_risk_profile` + `get_risk_analysis` + `get_positions` + `get_action_history(workflow_filter="strategy_design")` (parallel), optionally `set_risk_profile(profile="balanced")`
- Step 2: `run_optimization(optimization_type="min_variance"|"max_return", format="agent")`
- Step 3: `compare_scenarios(mode="optimization", scenarios="[{...}]", rank_by="trades_required"|"hhi", rank_order="asc")` — batch variant comparison (scenarios is a JSON string)
- Step 4: `run_whatif(target_weights={optimized}, format="agent")` for validation, `create_basket(name="...", tickers="AAPL,MSFT,...", weighting_method="custom", weights={...})` to save
- Step 5: `preview_rebalance_trades` → `preview_trade` → `execute_trade(preview_id=...)`

Audit: `record_workflow_action(workflow_name="strategy_design", recommendation_type="rebalance", recommendation_text="...", source_tool="run_optimization")` at step 4.

Breakpoints: after step 2 (optimization results), after step 3 (variant comparison).

---

## Critical Tool Parameter Details

**`compare_scenarios` rank_by keys** (must use these exact strings):
- whatif mode: `vol_delta`, `conc_delta`, `total_violations`, `factor_var_delta`
- optimization mode: `trades_required`, `total_violations`, `hhi`, `largest_weight_pct`
- NOT `sharpe_ratio` or `portfolio_volatility` — these don't exist

**`compare_scenarios` scenario format** (`scenarios` param is a JSON string, not a native list):
- whatif: `'[{"name": "...", "target_weights": {...}}, ...]'` or `'[{"name": "...", "delta_changes": {...}}, ...]'` — each scenario needs exactly one of target_weights/delta_changes
- optimization: `'[{"name": "...", "optimization_type": "min_variance"|"max_return"}, ...]'`

**`execute_trade` signature:** `execute_trade(preview_id="...")` — takes ONLY preview_id, NOT ticker/side/quantity

**Weight units:** `target_weights` uses decimals (0.24 = 24%). `delta_changes` values must be strings: `"+5%"`, `"-200bp"`, `"0.05"` (decimal as string). Parser calls `.strip()` — raw floats will break.

**Audit status flow:** `pending` → `accepted` → `executed` (or `pending` → `rejected`). Must transition through `accepted` before `executed`.

**`run_whatif` / `compare_scenarios` require risk limits:** If not configured, error. Workaround: `set_risk_profile(profile="balanced")` first.

**`check_exit_signals(ticker=...)` is single-ticker:** Loop for multiple tickers.

---

## Source Files (for Codex review)

These files contain the actual tool signatures and behavior that the skills must reference correctly:

| File | What to verify |
|------|---------------|
| `mcp_tools/compare.py` | `compare_scenarios()` signature, `_WHATIF_RANK_KEYS`, `_OPTIMIZATION_RANK_KEYS`, scenario format validation |
| `mcp_tools/rebalance.py` | `preview_rebalance_trades()` signature (target_weights, weight_changes, preview, format) |
| `mcp_tools/trading.py` | `preview_trade()` and `execute_trade(preview_id)` signatures |
| `mcp_tools/audit.py` | `_ALLOWED_WORKFLOWS` set, `record_workflow_action()` and `update_action_status()` signatures |
| `mcp_tools/whatif.py` | `run_whatif()` signature, `delta_changes` string format support |
| `mcp_tools/risk.py` | `get_risk_analysis()` format options |
| `mcp_tools/signals.py` | `check_exit_signals(ticker=...)` — single ticker only |
| `core/optimization.py` | `optimize_min_variance()`, `optimize_max_return()` — called by `run_optimization` |
| `api/memory/workspace/memory/skills/allocation-review.md` | Reference pattern for skill format (AI-excel-addin repo) |
| `api/memory/workspace/memory/skills/risk-review.md` | Reference pattern for audit integration (AI-excel-addin repo) |

---

## Files Changed

| File | Repo | Change |
|------|------|--------|
| `api/memory/workspace/memory/skills/hedging.md` | AI-excel-addin | NEW |
| `api/memory/workspace/memory/skills/scenario-analysis.md` | AI-excel-addin | NEW |
| `api/memory/workspace/memory/skills/strategy-design.md` | AI-excel-addin | NEW |

**No risk_module changes** — all three workflow names already in `_ALLOWED_WORKFLOWS`.

### Skill file skeleton (each file must follow this structure)

```markdown
---
name: <skill-name>
description: <one-line description>
---

# <Skill Title>

## When to Use
- ...

## When NOT to Use
- ...

## Workflow
1. Step 1 ...
2. Step 2 ...

## Output Format
- ...

## Tool Notes
- ...
```

---

## Key Design Decisions

1. **`compare_scenarios` replaces manual loops** — All three skills use the batch comparison tool instead of sequential `run_whatif` calls. Hedging compares hedge approaches, scenario-analysis compares what-if variants, strategy-design compares optimization variants.
2. **`preview_rebalance_trades` at execution** — Scenario analysis and strategy design use this to convert target weights to sequenced trade legs. Hedging uses direct `preview_trade(ticker=..., quantity=..., side=..., account_id=...)` since hedges are typically single-instrument trades.
3. **Hedging is instrument-agnostic** — Skill covers ETF, options, and futures hedges using different tool chains per instrument type, converging at `compare_scenarios` for impact comparison.
4. **Scenario analysis has no predefined templates** — Agent must construct `delta_changes` from natural language. Documented as a workaround, not a gap-filler.
5. **Strategy design saves as basket** — `create_basket` at step 4 persists the optimized weights for reuse. No strategy versioning beyond differently-named baskets.
6. **Correct `rank_by` keys** — Used actual valid keys from code (`vol_delta`, `trades_required`, `hhi`) not the conceptual keys from WORKFLOW_DESIGN.md.

---

## Verification

### Skill discovery
- After creating files, verify all 10 skills appear in the catalog (currently 7 skills at 1611 chars, adding 3 more — verify still under 2000 char limit)
- If catalog overflows, bump `max_catalog_chars` in `api/tools.py`

### Functional testing (live, against AI-excel-addin backend)
1. Start backend: `cd AI-excel-addin && uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile ... --ssl-certfile ...`
2. Test each skill:
   - "hedge my tech exposure" → agent should discover hedging skill, call `memory_read`
   - "what if I add 10% bonds" → scenario-analysis skill
   - "optimize my portfolio for min variance" → strategy-design skill
3. Verify: `memory_read` called for skill file, tool chain follows skill steps, audit trail recorded

### Catalog sizing
- Calculate new catalog size: current 7 skills ≈ 1611 chars + 3 new skills (each ~60-70 chars in catalog = ~200 chars more) ≈ 1811 chars
- Should fit within 2000 char limit, but verify
