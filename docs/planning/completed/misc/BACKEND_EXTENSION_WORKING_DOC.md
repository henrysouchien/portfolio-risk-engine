# Backend Extension Working Doc

**Purpose**: Track backend work needed to support frontend features and close data gaps.
**Last updated**: 2026-03-03

---

## Concrete — Ready to Build

### ~~B-001: What-If Response — Expose Scenario Metrics~~ ✓ DONE
**Completed**: Commit `937bc9e2`. Added `scenario_summary` dict to `WhatIfResult.to_api_response()` with raw numeric metrics (volatility, HHI, factor/idiosyncratic variance). Frontend reads from `scenarioSummary` instead of parsing formatted tables. Removed 5 always-N/A metric cards (expectedReturn, sharpeRatio, var95, var99, maxDrawdown), kept 3 real ones. HHI uses plain number formatting. Plan: `completed/WHATIF_SCENARIO_METRICS_PLAN.md`.

### ~~B-002: Stock Research — Real-Time Quote Endpoint~~ ✓ DONE
**Completed**: Wave 2d implementation (`4ae8115f`) + refactor (`941c92e0`). Search endpoint + enrichment (profile, quote, ratios, chart) wired via `StockService.search_stocks()` / `enrich_stock_data()`. Plans: `completed/STOCK_RESEARCH_FMP_WIRING_PLAN.md`, `completed/STOCK_ENRICHMENT_REFACTOR_PLAN.md`.

### ~~B-003: FactorRiskModel — Performance Tab Metrics~~ ✓ DONE
**Completed**: Commit `dbcee8c9` (Wave 2e). Wired real Alpha, IR, R² into FactorRiskModel Performance tab. No backend changes needed — data already available via `usePerformance()` + `useRiskAnalysis()`. Plan: `completed/FACTOR_PERFORMANCE_TAB_PLAN.md`.

### ~~B-004: Holdings Enrichment — Day Change + Sparkline~~ ✓ ALREADY DONE
**Verified**: 2026-03-03. `enrich_positions_with_market_data()` in `portfolio_service.py` already batch-fetches FMP quotes (day_change, day_change_percent) and 45-day historical (trend sparkline). Wired into `/api/positions/holdings` route. Frontend displays all fields correctly.

### ~~B-005: Holdings Enrichment — Per-Position Volatility~~ ✓ ALREADY DONE
**Verified**: 2026-03-03. Same `enrich_positions_with_market_data()` computes annualized volatility from 45-day historical returns per ticker. Shows correctly in Holdings view (e.g. DSU 5.5%, MSCI 42.9%).

### ~~B-006: DataFrame Serialization — Use `orient='records'`~~ ✓ DONE
**Completed**: Commit `f2a48bcc`. Added opt-in `orient` param to `_convert_to_json_serializable()` (default `'dict'` = backward-compatible). Only whatif.py and optimization.py structured fields use `orient='records'`. Legacy fields, risk.py matrices, and all other callers untouched. 4 rounds of Codex review to get the blast radius right. Plan: `completed/DATAFRAME_SERIALIZATION_FIX_PLAN.md`.

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

### ~~B-013: AI Insights on Metric Cards~~ ✓ DONE
**Completed**: Commit `14f795bd`. Option (B) — client-side derived insights from real metrics. Replaced hardcoded text/confidence with threshold-based text from real alpha, Sharpe, volatility, drawdown, beta. Alpha/Sharpe labels now dynamic. Removed fake confidence scores and "Machine learning" header. Plan: `completed/AI_INSIGHTS_METRICS_PLAN.md`.

### ~~B-014: Performance View — Target Prices / AI Content~~ ✓ DONE
**Completed**: Commit `3f14a56b`. Added `enrich_attribution_with_analyst_data()` to `portfolio_service.py` — fetches FMP `price_target_consensus`, `price_target`, `analyst_grades` per ticker via ThreadPoolExecutor. Frontend replaced hardcoded AAPL/MSFT/NVDA with real `security_attribution` data from portfolio. Plan: `completed/PERFORMANCE_ANALYST_DATA_PLAN.md`.

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

### ~~B-017: Per-Position Alerts~~ ✓ DONE
**Completed**: Commit `f3b15bd9`. Passed `monitor_positions` and real `cache_info` to `generate_position_flags()` in holdings route. Added `portfolio_alerts` + `portfolio_alert_details` to response. No frontend changes needed — badge already rendered when `alerts > 0`. Plan: `completed/PER_POSITION_ALERTS_PLAN.md`.

### ~~B-018: Notification System~~ ✓ DONE
**Completed**: Commit `1505c1f1`. Option (B) — frontend composition layer composing `useSmartAlerts()` + `usePendingUpdates()` into `useNotifications()` hook. No new backend endpoints needed (only one backend fix: alert ID uniqueness in `_build_alert_id()`). alertMappings.ts maps ~20 flag types to titles + navigation actions. localStorage persistence for dismissed/read IDs. Session-only dismissal for pending updates. Plan: `completed/NOTIFICATION_CENTER_WIRING_PLAN.md`.

---

## Summary

| ID | Item | Status | Effort |
|----|------|--------|--------|
| B-001 | What-If scenario metrics | **DONE** (`937bc9e2`) | Small |
| B-002 | Stock Research quotes | **DONE** (`941c92e0`) | Small-Medium |
| B-003 | FactorRiskModel perf tab | **DONE** (`dbcee8c9`) | Medium |
| B-004 | Holdings day change + sparkline | **DONE** (already working) | Medium |
| B-005 | Holdings per-position volatility | **DONE** (already working) | Small-Medium |
| B-006 | DataFrame serialization orient='records' | **DONE** (`f2a48bcc`) | Small |
| B-010 | Smart Alerts / Risk Flags | In progress (parallel session) | Medium |
| B-011 | Market Intelligence | Needs design decision | Medium-High |
| B-012 | AI Recommendations | Needs design decision | High |
| B-013 | AI Insights on metrics | **DONE** (`14f795bd`) | Medium |
| B-014 | Performance target prices | **DONE** (`3f14a56b`) | Medium |
| B-015 | Backtesting engine | Needs design decision | High |
| B-016 | Per-position risk/AI score | Needs design decision | Medium-High |
| B-017 | Per-position alerts | **DONE** (`f3b15bd9`) | Medium |
| B-018 | Notification system | **DONE** (`1505c1f1`) | Medium |
