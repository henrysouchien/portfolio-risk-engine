# Backend Extension Working Doc

**Purpose**: Track backend work needed to support frontend features and close data gaps.
**Last updated**: 2026-03-02

---

## Concrete — Ready to Build

### B-001: What-If Response — Expose Scenario Metrics
**Source**: Wave 3 Phase A verification (Scenario Analysis N/A metrics)
**Problem**: `WhatIfResult.to_api_response()` comments out `scenario_metrics` (line 650 of `core/result_objects/whatif.py`). The `risk_comparison` table only has 5 metrics (Volatility, Max Weight, Factor Var %, Market Var %, Max Industry Var %). Frontend can't show Expected Return, Sharpe Ratio, or VaR.
**Fix**: Expose key fields from `scenario_metrics` (a `RiskAnalysisResult`) in the API response — at minimum: `volatility_annual`, `var_95`, `sharpe_ratio`, `expected_return`. Also: `get_risk_comparison_table()` formats values as strings (`"18.5%"`) — frontend `toNumber()` can't parse them. Either add raw numeric fields or use `comparison_analysis.risk_comparison` (already has raw values).
**Frontend ready?** Yes — `deriveMetricsFromComparison()` in `ScenarioAnalysis.tsx` just needs the data.
**Effort**: Small

### B-002: Stock Research — Real-Time Quote Endpoint
**Source**: Wave 2d
**Problem**: `StockLookupContainer` has TODOs for real-time price, market cap, volume. FMP has the data but it's not wired to this endpoint.
**Fix**: Add FMP real-time quote data (price, market cap, volume, day change) to `/api/direct/stock` response or create a lightweight quote endpoint.
**Frontend ready?** Yes — `StockLookupContainer` has placeholders.
**Effort**: Small-Medium

### B-003: FactorRiskModel — Performance Tab Metrics
**Source**: Wave 2e
**Problem**: FactorRiskModel Performance tab shows hardcoded values. Needs: Factor Alpha (from `historical_analysis`), Information Ratio (alpha / tracking error), R² (from `variance_decomposition.factor_variance / 100`). t-stat needs regression p-values — low priority.
**Fix**: Compute and include in `/api/analyze` response. R² can be derived from existing variance decomposition. Factor Alpha and IR need computation in `portfolio_risk.py` or `core/portfolio_analysis.py`.
**Frontend ready?** Yes — FactorRiskModelContainer has adapter mapping TODOs.
**Effort**: Medium

### B-004: Holdings Enrichment — Day Change + Sparkline
**Source**: Remaining Holdings Fields (Phase 2 working doc)
**Problem**: `dayChange`, `dayChangePercent`, and `trend` (sparkline data) always return 0/empty.
**Fix**: Add FMP real-time quote (day change) and historical price series (sparkline) to `/api/positions/holdings` response. FMP endpoints exist — need to batch-fetch for all positions.
**Frontend ready?** Yes — HoldingsView renders these fields, just gets zeros.
**Effort**: Medium (batch FMP calls for all holdings)

### B-005: Holdings Enrichment — Per-Position Volatility
**Source**: Remaining Holdings Fields
**Problem**: `volatility` per-holding always 0. Data exists at portfolio level in `df_stock_returns` but not surfaced per-position.
**Fix**: Compute annualized volatility per ticker from `df_stock_returns` and include in holdings response.
**Frontend ready?** Yes.
**Effort**: Small-Medium

### B-006: DataFrame Serialization — Use `orient='records'`
**Source**: Scenario Analysis N/A metrics investigation
**Problem**: `_convert_to_json_serializable()` in `core/result_objects/_helpers.py` calls `df.to_dict()` without `orient` param, producing column-oriented dicts (`{"Column": {"0": value}}`) instead of row arrays (`[{"Column": value}]`). Docstrings and comments say "row format" / `List[Dict]` but the actual output is a DataFrame-style dict. Frontend had to add `dataFrameToRows()` workaround in ScenarioAnalysis.
**Fix**: Change `df_copy.to_dict()` → `df_copy.to_dict(orient='records')` in `_convert_to_json_serializable()`. Audit all callers — this affects every result object that serializes DataFrames (whatif, optimization, risk, etc.). Frontend `dataFrameToRows()` becomes a defensive fallback.
**Frontend ready?** Yes — `dataFrameToRows()` already handles both shapes.
**Effort**: Small (code change trivial, but needs integration testing across all API responses)

---

## Needs Design Decision — Evaluate First

### B-010: Smart Alerts / Risk Flags → Frontend
**Source**: Wave 3b
**Problem**: Overview shows hardcoded alert badges. Backend computes rich risk flags in `core/*_flags.py` (20+ flag files) but these only surface in MCP agent-format responses, not in REST API.
**Options**:
  - (A) Add flags to existing `/api/analyze` response
  - (B) New `/api/alerts` endpoint that aggregates flags from multiple tools
  - (C) Derive client-side from existing risk data
**Decision**: TBD
**Effort**: Medium

### B-011: Market Intelligence
**Source**: Wave 3a
**Problem**: Overview "Market Intelligence" section shows hardcoded demo events.
**Options**:
  - (A) FMP `get_news` + `get_market_context` via new REST endpoint
  - (B) Surface MCP tool output through REST
  - (C) Remove section from UI
**Decision**: TBD
**Effort**: Medium-High (A/B), None (C)

### B-012: AI Recommendations
**Source**: Wave 3d
**Problem**: Overview shows 3 hardcoded ML recommendations (Rebalance, Hedge, Opportunity) with fake confidence scores.
**Options**:
  - (A) Server-side: compose from optimization + factor recommendations + risk flags
  - (B) Client-side: derive from existing data (simpler but less intelligent)
  - (C) Remove from UI until real AI pipeline exists
**Decision**: TBD
**Effort**: High (A), Medium (B), None (C)

### B-013: AI Insights on Metric Cards
**Source**: Wave 3e
**Problem**: Per-metric AI commentary ("Portfolio shows strong risk-adjusted returns", 92% confidence) is entirely hardcoded.
**Options**:
  - (A) Server-side interpretive text in analysis response
  - (B) Client-side computed from real metric values (e.g., Sharpe > 1.5 → "Excellent risk-adjusted returns")
  - (C) Remove AI commentary layer
**Decision**: TBD
**Effort**: High (A), Medium (B), None (C)

### B-014: Performance View — Target Prices / AI Content
**Source**: Wave 3f
**Problem**: Top Contributors/Detractors section has hardcoded stock targets (AAPL Buy $225, MSFT Strong Buy $450, etc.) and AI momentum scores.
**Options**:
  - (A) Wire FMP analyst consensus (target prices, ratings) — endpoints exist
  - (B) Remove AI layer, keep real contributor/detractor data from attribution
  - (C) Remove entire section
**Decision**: TBD
**Effort**: Medium (A), Small (B), None (C)

### B-015: Backtesting Engine
**Source**: Wave 3g
**Problem**: StrategyBuilder backtesting uses mock timer — no backend backtesting capability.
**Options**:
  - (A) Build historical backtesting engine (run portfolio through historical periods)
  - (B) Keep disabled with "Coming soon"
**Decision**: TBD
**Effort**: High (A), None (B)

### B-016: Per-Position Risk Score / AI Score
**Source**: Remaining Holdings Fields
**Problem**: `riskScore` and `aiScore` per-holding always 0. No clear product spec.
**Options**:
  - (A) Define composite per-position risk (concentration + volatility + drawdown)
  - (B) Remove from UI
**Decision**: TBD
**Effort**: Medium-High (A), None (B)

### B-017: Per-Position Alerts
**Source**: Remaining Holdings Fields
**Problem**: `alerts` count per-holding always 0. Infrastructure exists in `core/*_flags.py`.
**Fix**: Derive per-ticker alert count from risk/position flags. Similar to B-010 but per-position.
**Decision**: TBD (depends on B-010 approach)
**Effort**: Medium

### B-018: Notification System
**Source**: Wave 3c
**Problem**: Bell icon shows hardcoded notifications. No backend notification infrastructure.
**Options**:
  - (A) Event-driven notifications (webhook-triggered)
  - (B) Polling-derived from risk flags + pending updates
  - (C) Remove notification center
**Decision**: TBD
**Effort**: High (A), Medium (B), None (C)

---

## Summary

| ID | Item | Status | Effort |
|----|------|--------|--------|
| B-001 | What-If scenario metrics | Ready to build | Small |
| B-002 | Stock Research quotes | Ready to build | Small-Medium |
| B-003 | FactorRiskModel perf tab | Ready to build | Medium |
| B-004 | Holdings day change + sparkline | Ready to build | Medium |
| B-005 | Holdings per-position volatility | Ready to build | Small-Medium |
| B-006 | DataFrame serialization orient='records' | Ready to build | Small |
| B-010 | Smart Alerts / Risk Flags | Needs design decision | Medium |
| B-011 | Market Intelligence | Needs design decision | Medium-High |
| B-012 | AI Recommendations | Needs design decision | High |
| B-013 | AI Insights on metrics | Needs design decision | Medium-High |
| B-014 | Performance target prices | Needs design decision | Medium |
| B-015 | Backtesting engine | Needs design decision | High |
| B-016 | Per-position risk/AI score | Needs design decision | Medium-High |
| B-017 | Per-position alerts | Needs design decision | Medium |
| B-018 | Notification system | Needs design decision | High |
