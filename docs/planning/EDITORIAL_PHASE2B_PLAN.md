# Overview Editorial Pipeline — Phase 2B Implementation Plan: Generator Expansion

**Status**: DRAFT — pending Codex review
**Created**: 2026-04-13
**Inputs**:
- Architecture spec: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md` (§14 Phase 2)
- Phase 1 plan pattern: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md`
- Existing generators: `core/overview_editorial/generators/` (concentration, risk, performance)

This plan covers Phase 2B: adding four new generators (Income, Trading, Factor, Tax Harvest) to the existing editorial pipeline. Each drops into the pipeline without architectural changes.

**Timeline**: ~2-3 weeks (4 generators are fully independent + thin policy integration pass).

---

## 1. Plan Purpose

Phase 1 shipped 3 generators. The design doc lists 8 generator categories. Phase 2B adds 4 more, expanding editorial coverage to income, trading behavior, factor exposure, and tax optimization. Each generator follows the exact Phase 1 pattern and drops into the existing pipeline.

**Goals**:
- Four new generators, each independently committable
- Orchestrator expands data gathering to include new sources (parallel via ThreadPoolExecutor)
- Policy layer registers new generators (no scoring formula changes)
- Confidence/source heuristics updated for variable generator counts

**Non-goals**:
- Changes to wire schema, REST endpoint, frontend rendering, or LLM arbiter
- New candidate slot types
- Changes to editorial memory structure or scoring weights

---

## 2. Sub-phase Summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| G1 | Income Generator + orchestrator income data source | Generator + `_gather_income` + `_normalize_income` | ~3 days | Phase 1 |
| G2 | Trading Generator + orchestrator trading data source | Generator + `_gather_trading` + `_normalize_trading` + service helper | ~3 days | Phase 1 |
| G3 | Factor Generator + orchestrator factor data source | Generator + expanded `_normalize_risk()` + `_derive_factor_from_risk()` | ~4 days | Phase 1 |
| G4 | Tax Harvest Generator + orchestrator tax data source | Generator + `_gather_tax_harvest` + `_normalize_tax_harvest` + service helper | ~3 days | Phase 1 |
| P1 | Policy layer update + confidence heuristic fix | Register new generators, fix hardcoded `== 3` | ~1 day | Any subset of G1-G4 |

**All four generators are independent of each other.** They can be implemented in any order or in parallel.

---

## 3. Dependency Graph

```
Phase 1 (complete)
  ↓
G1 (Income)  ──┐
G2 (Trading) ──┤
G3 (Factor)  ──┼──> P1 (policy registration + confidence fix)
G4 (Tax)     ──┘
```

---

## 4. Cross-Cutting Concerns

### 4.1 Data access — raw-dict vs agent-format

Two MCP tool categories:
- **Raw-dict tools** (Income, Tax Harvest): MCP tool returns a plain `dict`. Standalone `_build_*_snapshot()` functions produce compact snapshot dicts.
- **Agent-format tools** (Trading, Factor): MCP tool returns a result object with `.get_agent_snapshot()`.

Both patterns normalize into `{"snapshot": dict, "flags": list}` in the orchestrator. Generators read `context.tool_snapshot("<name>")` uniformly.

### 4.2 Orchestrator data gathering

Each new data source gets `_gather_<name>()` + `_normalize_<name>()` following the existing pattern. ThreadPoolExecutor `max_workers` increases to accommodate new parallel lanes:
- If Phase 2A has already landed (events lane): 4 → 7 (3 new parallel lanes: income, trading, tax_harvest; factor is synchronous derivation)
- If Phase 2B ships first: 3 → 6 (3 new parallel lanes; factor is synchronous)

**Critical constraint**: New data sources must NOT call raw MCP tool wrappers directly. They use **service-layer** helpers — NOT `actions/` wrappers (which would invert the `route → action → core` call direction). The orchestrator lives in `core/`, so it can call `services/` but not `actions/` or `mcp_tools/`. Where existing service-layer or result-cache paths exist (e.g., income already has `result_cache.py:723`), reuse them.

### 4.3 Factor generator — reuses risk result

The Factor Generator does NOT make a separate API call. It derives factor-specific data from the risk analysis result already gathered by `_gather_risk()`. The raw `RiskAnalysisResult.get_agent_snapshot()` (verified at `core/result_objects/risk.py:276`) includes `portfolio_factor_betas`, `variance_decomposition` (with `factor_breakdown_pct`, `factor_pct`, `idiosyncratic_pct`), and `beta_exposure_checks_table`.

**Problem**: The current `_normalize_risk()` at `orchestrator.py:64` drops these factor-level fields — it only keeps `volatility_annual`, `herfindahl`, `risk_drivers`, `leverage`, `factor_variance_pct`, and `risk_limit_violations`. The existing orchestrator test at `test_orchestrator.py:103` locks this normalized shape.

**Solution**: G3 expands `_normalize_risk()` to also pass through `portfolio_factor_betas`, `variance_decomposition`, and `beta_exposure_checks_table` into the risk snapshot. This is a **risk snapshot contract expansion** (additive, backward-compatible). The orchestrator test must be updated to reflect the new fields. After this expansion, a synchronous `_derive_factor_from_risk(tool_results["risk"])` call reads the expanded risk `{snapshot, flags}` dict and produces a separate `{snapshot, flags}` entry for `tool_results["factor"]`. No raw `RiskAnalysisResult` object storage needed.

**Note**: `factor_pct` and `idiosyncratic_pct` in the risk agent snapshot are 0-1 fractions, not 0-100 percentages. The factor generator must multiply by 100 for display.

### 4.4 InsightCandidate categories

`InsightCandidate.category` Literal already includes `"income"`, `"trading"`, `"factor"`, `"tax"` (added during Phase 1 for forward compatibility). No model changes needed.

### 4.5 Confidence and source heuristics

Current `_confidence()` AND `_source()` both use hardcoded `== 3` at `policy.py:284`. Both must be updated to core-source logic:

```python
_CORE_SOURCES = {"positions", "risk", "performance"}

def _confidence(self, context):
    core_loaded = sum(1 for s in _CORE_SOURCES if context.data_status.get(s) == "loaded")
    if core_loaded == 3: return "high"
    if core_loaded >= 1: return "partial"
    return "summary only"

def _source(self, context):
    core_loaded = sum(1 for s in _CORE_SOURCES if context.data_status.get(s) == "loaded")
    if core_loaded == 3: return "live"
    if core_loaded >= 1: return "mixed"
    return "summary"
```

Four new sources are enrichment, not requirements. A portfolio with no transaction history (trading unavailable) or no dividends (income empty) still gets "high" confidence. This logic is shared with Phase 2A — whichever ships first implements it.

### 4.6 Generator failure isolation

Every generator wraps `generate()` in `try/except Exception` and returns `GeneratorOutput()` on failure. Established pattern from Phase 1.

---

## 5. Sub-phase G1 — Income Generator

### 5.1 Goal

Surface portfolio yield, upcoming dividends, income pace, and dividend warnings.

### 5.2 Data source

**Existing infrastructure**: Income already has an L2 result cache at `services/portfolio/result_cache.py:723` (`get_income_projection_result_snapshot()`) and a transport-neutral action at `actions/income_projection.py:642`. The orchestrator should reuse this cache path — NOT call `mcp_tools/income.py` directly.

**Orchestrator data path**: `_gather_income()` calls `get_income_projection_result_snapshot()` from `result_cache.py` with a builder callable. The builder delegates to the income projection workflow at the service/action layer (the same path that the existing MCP tool and REST endpoint use). This follows the same pattern as the existing risk/performance data sources in the orchestrator.

**Snapshot building**: The `_build_income_snapshot()` function currently lives in `mcp_tools/income.py`. Since `services/` cannot import `mcp_tools/` (architecture boundary at `test_architecture_boundaries.py:161`), the snapshot builder must be relocated to a service-layer module (e.g., `services/income_helpers.py`) or inlined in the orchestrator's `_normalize_income()`. The existing result cache builder returns the raw projection dict; `_normalize_income()` handles the `{snapshot, flags}` transformation.

**Snapshot shape**:
```python
{
    "status": str,
    "verdict": str,
    "annual_income": float,
    "monthly_income_avg": float,
    "portfolio_yield_on_value": float,  # percentage points (3.31 = 3.31%)
    "portfolio_yield_on_cost": float,
    "total_portfolio_value": float,
    "holding_count": int,
    "income_holding_count": int,
    "top_contributors": [{"ticker": str, "annual_income": float, "yield_on_cost": float, "frequency": str}],
    "upcoming_dividends": [{"ticker": str, "ex_date": str, "amount": float}],
    "warning_count": int,
    "warnings": [str],
}
```

### 5.3 Candidates emitted

| Slot | When | Content |
|---|---|---|
| `metric` (portfolio_yield) | `annual_income > 0` | title="Portfolio Yield", value=f"{yield:.1f}%" |
| `metric` (next_dividend) | upcoming dividends non-empty | title="Next Dividend", value=next ex_date ticker |
| `lead_insight` | `annual_income > 0 and income_holding_count >= 3` | "On track for $X income this year" |
| `lead_insight` | `warning_count > 0` | "Income pace below target — N positions cut dividends" |
| `attention_item` | upcoming dividends within 7 days for large positions | urgency="act", ex-div approaching |
| `attention_item` | variable dividend warnings | urgency="watch" |
| `margin_annotation` | yield > 2% | "Ask about income strategy" |

### 5.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/income.py` | Income insight generator | ~180 |
| `tests/core/overview_editorial/test_income_generator.py` | Unit tests | ~200 |

### 5.5 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `_normalize_income()`, `_gather_income()`, extend ThreadPoolExecutor |
| `tests/core/overview_editorial/test_orchestrator.py` | Add income gathering tests |

### 5.6 Tests (18 tests)

- Empty/None/failed snapshot → empty output
- Zero-income portfolio → no lead_insight
- Positive income → metric + lead_insight
- High yield (>4%) → high relevance
- Upcoming dividends → attention_item
- Dividend warnings → attention_item
- Material income → artifact directive + margin annotation
- Boundary conditions on scoring thresholds
- Various snapshot shapes (missing fields, partial data)

### 5.7 Acceptance gate

- Generator handles None, empty, failed status gracefully
- All metric candidates have valid `content.id`, `content.title`, `content.value`
- Lead insight candidates have `headline` and `exit_ramps`
- Orchestrator `_gather_income` returns correct tuple

### 5.8 Rollback

Delete generator + test. Revert orchestrator changes.

---

## 6. Sub-phase G2 — Trading Generator

### 6.1 Goal

Surface recent trade quality, win rate, revenge trading flags, best/worst trades.

### 6.2 Data source

**Tool**: `get_trading_analysis()` in `mcp_tools/trading_analysis.py` — agent-format tool.
**Snapshot**: `FullAnalysisResult.get_agent_snapshot()` in `trading_analysis/models.py`.

**Orchestrator data path**: Create a new **service-layer** helper `services/trading_service.py:get_trading_snapshot_for_overview()`. NOT an `actions/` wrapper (which would invert `route → action → core`). The service helper encapsulates transaction loading + `TradingAnalyzer` construction + `run_full_analysis()` + `get_agent_snapshot()`. The orchestrator calls this helper from `_gather_trading()`.

**Architecture note**: `services/` cannot import `mcp_tools/` (boundary test at `test_architecture_boundaries.py:161`). The trading service helper must use `trading_analysis/` (the core trading module) directly — NOT delegate to `mcp_tools/trading_analysis.py`. `TradingAnalyzer` and `FullAnalysisResult` live in `trading_analysis/models.py`, which is importable from `services/`.

**Snapshot shape** (key fields):
```python
{
    "verdict": str,  # "excellent", "strong", "decent", "mediocre", "poor", "failing"
    "trades": {"total": int, "total_pnl_usd": float, "win_rate_pct": float},
    "grades": {"overall": str, "edge": str, "sizing": str, "timing": str, "discipline": str},
    "performance": {"net_pnl": float, "profit_factor": float, "expectancy": float},
    "behavioral": {"revenge_trade_count": int, "averaging_down_count": int},
    "top_winners": [...],
    "top_losers": [...],
}
```

**Note**: The snapshot shape above comes from `FullAnalysisResult.get_agent_snapshot()`. The service helper at `services/trading_service.py` handles transaction loading and produces this shape.

### 6.3 Candidates emitted

| Slot | When | Content |
|---|---|---|
| `metric` (win_rate) | `trades.total >= 5` | title="Win Rate", value=f"{rate:.0f}%" |
| `metric` (edge_grade) | grades present | title="Edge Score", value=grades.edge |
| `lead_insight` | good grades (A/B) + 10+ trades | "Trading edge has improved" |
| `lead_insight` | poor grades (D/F) + 10+ trades | "Trading quality is deteriorating" |
| `attention_item` | revenge_trade_count > 0 | urgency="alert", revenge trading detected |
| `attention_item` | overall grade D/F | urgency="act", edge is poor |
| `margin_annotation` | trading data exists | "Review recent trade quality" |

### 6.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/trading.py` | Trading insight generator | ~200 |
| `tests/core/overview_editorial/test_trading_generator.py` | Unit tests | ~220 |
| `services/trading_service.py` | Service-layer helper for overview trading snapshot | ~80 |

### 6.5 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `_normalize_trading()`, `_gather_trading()` |
| `tests/core/overview_editorial/test_orchestrator.py` | Add trading gathering tests |

### 6.6 Tests (18 tests)

- Empty/None/failed → empty output
- <5 trades → no metrics
- Good/poor grades → appropriate lead_insight
- Revenge trades → alert attention_item
- Grade boundary conditions
- Various snapshot shapes

### 6.7 Rollback

Delete generator, test, service helper. Revert orchestrator.

---

## 7. Sub-phase G3 — Factor Generator

### 7.1 Goal

Surface factor exposure drift, unintended bets, factor concentration.

### 7.2 Data source

**Approach**: Reuse risk analysis result (already gathered by `_gather_risk`). The risk result's `get_agent_snapshot()` includes `portfolio_factor_betas`, `variance_decomposition`, `beta_exposure_checks_table`. No separate API call needed.

**Factor snapshot** (derived from the normalized risk snapshot in `tool_results["risk"]["snapshot"]`):
```python
{
    "portfolio_factor_betas": {"market": 1.15, "growth": 0.85, ...},
    "factor_variance_pct": 72.0,  # NOTE: risk snapshot stores factor_pct as 0-1 fraction (0.72), multiply by 100 for display
    "factor_breakdown_pct": {"market": 0.45, "growth": 0.15, ...},  # also 0-1 fractions in source
    "dominant_factor": "market",
    "dominant_factor_pct": 45.0,
    "factor_concentration_score": float,  # HHI of factor_breakdown_pct, computed by _derive_factor_from_risk
    "beta_exposure_violations": [...],
}
```

**Orchestrator**: After the ThreadPoolExecutor completes, synchronous `_derive_factor_from_risk(tool_results["risk"])` reads the **normalized** risk `{snapshot, flags}` dict and produces a separate `{snapshot, flags}` entry under `tool_results["factor"]`. No raw `RiskAnalysisResult` object is stored — this preserves the existing normalized contract.

### 7.3 Candidates emitted

| Slot | When | Content |
|---|---|---|
| `metric` (dominant_factor) | dominant factor exists | title="Dominant Factor", value=f"{name} {pct:.0f}%" |
| `metric` (factor_concentration) | score > 0 | title="Factor Concentration", value=f"{score:.2f}" |
| `lead_insight` | dominant_factor_pct >= 40 | "{Factor} is {pct}% of portfolio risk — intentional?" |
| `lead_insight` | unintended tilt (non-market beta > 0.3) | "Unintended {factor} tilt detected" |
| `attention_item` | beta_exposure_violations non-empty | urgency="alert", factor limit violation |
| `attention_item` | dominant_factor_pct >= 50 | urgency="act", factor dominates |
| `margin_annotation` | factor data interesting | "Ask about factor exposure" |

### 7.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/factor.py` | Factor insight generator | ~180 |
| `tests/core/overview_editorial/test_factor_generator.py` | Unit tests | ~200 |

### 7.5 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `_derive_factor_from_risk(risk_tool_result)` post-processing (reads normalized snapshot, no raw result storage) |
| `tests/core/overview_editorial/test_orchestrator.py` | Add factor derivation tests |

### 7.6 Tests (16 tests)

- Empty/None → empty output
- Low factor concentration → metric only
- High dominant factor → lead_insight
- Unintended tilt detection
- Factor limit violations → alert
- Dominant >50% → act
- Boundary conditions

### 7.7 Risk: Overlap with risk generator

Risk generator shows `factor_variance_pct` as context on risk metrics. Factor generator surfaces factor DETAIL (which factors, how concentrated). Different editorial purpose — no conflict.

### 7.8 Rollback

Delete generator + test. Revert orchestrator.

---

## 8. Sub-phase G4 — Tax Harvest Generator

### 8.1 Goal

Surface harvest opportunities, wash sale windows, estimated savings.

### 8.2 Data source

**Tool**: `suggest_tax_loss_harvest()` in `mcp_tools/tax_harvest.py` — raw-dict tool.
**Snapshot builder**: `_build_tax_harvest_snapshot()` — standalone function.

**Snapshot shape**:
```python
{
    "status": str,
    "verdict": str,
    "total_harvestable_loss": float,
    "short_term_loss": float,
    "long_term_loss": float,
    "candidate_count": int,
    "top_candidates": [{"ticker": str, "total_loss": float, "wash_sale_risk": bool}],
    "wash_sale_ticker_count": int,
    "wash_sale_tickers": [str],
    "data_coverage_pct": float,
}
```

**Orchestrator data path**: Create a new **service-layer** helper `services/tax_harvest_service.py:get_tax_harvest_snapshot_for_overview()` — NOT an `actions/` wrapper (same layering rationale as Trading). The service helper encapsulates FIFO lot loading + harvest analysis + snapshot transformation.

**Architecture note**: `services/` cannot import `mcp_tools/` (boundary test). The `_build_tax_harvest_snapshot()` function currently lives in `mcp_tools/tax_harvest.py:851`. It must be either relocated to a service-layer module (e.g., `services/tax_harvest_helpers.py`) or its logic inlined in the service helper / orchestrator normalizer. The tax harvest core logic (`core/tax_harvest/` or equivalent) is importable from `services/`.

**Snapshot shape** also includes `positions_analyzed` and `positions_with_lots` (omitted from initial draft — verified at `mcp_tools/tax_harvest.py:962`).

### 8.3 Candidates emitted

| Slot | When | Content |
|---|---|---|
| `metric` (harvestable_losses) | `total_harvestable_loss != 0` | title="Harvestable Losses", value=f"${abs(loss):,.0f}" |
| `metric` (harvest_candidates) | `candidate_count > 0` | title="Harvest Candidates", value=f"{count} positions" |
| `lead_insight` | `candidate_count >= 3 and loss >= $1K` | "N positions have $X in harvestable losses" |
| `lead_insight` | Q4 seasonal urgency | "Tax deadline approaching — $X in harvestable losses" |
| `attention_item` | wash sale risk | urgency="act", window expiring |
| `attention_item` | large harvest (>$5K) | urgency="act", large opportunity |
| Exit ramps | harvest exists | Navigate to tax harvest scanner + chat prompt |
| `margin_annotation` | harvest exists | "Review tax harvest opportunities" |

**Seasonal urgency boost**: In Q4 (Oct-Dec), urgency scores boost for tax candidates. Generator checks `context.generated_at.month >= 10`.

### 8.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/generators/tax_harvest.py` | Tax harvest generator | ~180 |
| `tests/core/overview_editorial/test_tax_harvest_generator.py` | Unit tests | ~200 |
| `services/tax_harvest_service.py` | Service-layer helper for overview tax harvest snapshot | ~80 |

### 8.5 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/orchestrator.py` | Add `_normalize_tax_harvest()`, `_gather_tax_harvest()` |
| `tests/core/overview_editorial/test_orchestrator.py` | Add tax harvest gathering tests |

### 8.6 Tests (18 tests)

- Empty/None/failed → empty output
- No candidates → no lead_insight
- Multiple candidates → metric + lead_insight
- Wash sale risk → attention_item
- Large harvest → attention_item
- Q4 seasonal urgency boost
- Exit ramps include tax harvest scanner
- Boundary conditions

### 8.7 Rollback

Delete generator, test, service helper. Revert orchestrator.

---

## 9. Sub-phase P1 — Policy Integration

### 9.1 Goal

Register all new generators and fix confidence/source heuristics.

### 9.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/__init__.py` | Export 4 new generator classes |
| `core/overview_editorial/policy.py` | Register generators; update BOTH `_confidence()` AND `_source()` to core-source logic |
| `tests/core/overview_editorial/test_policy.py` | Update for 7-generator default, new confidence/source logic |

### 9.3 Confidence and source heuristic

Change BOTH `_confidence()` AND `_source()` (both hardcoded `== 3` at `policy.py:284`) to core-source check:
```python
_CORE_SOURCES = {"positions", "risk", "performance"}
core_loaded = sum(1 for s in _CORE_SOURCES if context.data_status.get(s) == "loaded")
# _confidence: 3 → "high", >=1 → "partial", 0 → "summary only"
# _source: 3 → "live", >=1 → "mixed", 0 → "summary"
```

If Phase 2A has already shipped, this change is already done. P1 only needs to register generators + update tests.

### 9.4 Generator registration

Default list grows from 3 to 7 generators.

### 9.5 Tests (8 tests)

- Default list includes all 7
- Confidence "high" when 3 core loaded + supplementary missing
- Confidence "partial" when 1 core loaded
- Confidence "summary only" when 0 core loaded
- Full pipeline integration with mixed data availability

### 9.6 Rollback

Revert `__init__.py`, `policy.py`, test changes. Generators remain as standalone files.

---

## 10. Implementation Order

**Recommended**: G1 (Income) → G4 (Tax Harvest) → G2 (Trading) → G3 (Factor) → P1

**Rationale**:
1. G1 is simplest data path (standalone snapshot builder)
2. G4 is structurally similar (also raw-dict)
3. G2 requires service-layer helper (more work)
4. G3 is unique (derives from risk result, no new API call)
5. P1 is thin integration once generators are ready

**Alternative**: Register each generator incrementally as it ships (P1 after each G*).

---

## 11. Summary

| Item | New Files | Modified Files | Tests | Duration |
|---|---|---|---|---|
| G1 Income | 2 | 2 | 18 | ~3 days |
| G2 Trading | 3 | 2 | 18 | ~3 days |
| G3 Factor | 2 | 2 | 16 | ~4 days |
| G4 Tax Harvest | 3 | 2 | 18 | ~3 days |
| P1 Policy | 0 | 3 | 8 | ~1 day |
| **Total** | **10** | **11** | **78** | **~14 days** |

---

## 12. Cross-Cutting Risks

| Risk | Mitigation |
|---|---|
| Data source latency increases brief generation | ThreadPoolExecutor parallel; worst latency dominates, not sum |
| New generators flood metric strip | Already capped at 6 by `select_slots(limit=6)` |
| New categories dilute memory_fit scoring | Users with no preference get default 0.3; can set explicit preferences |
| Service helpers for trading/tax duplicate MCP logic | Keep helpers thin; delegate to existing functions |
| Factor derivation reads normalized risk snapshot | Synchronous post-processing after ThreadPoolExecutor; no thread safety concern |
