# Futures Portfolio Integration — High-Level Design

## Overview

Futures are fundamentally different from equities in pricing, sizing, symbols, currency, and risk decomposition — but they are part of the same portfolio and must integrate into holdings, performance, risk analysis, and trading views.

This document outlines the architecture for futures support: what stays separate, what integrates, and how the pieces connect.

## Architecture: Three-Layer Split

Following existing package boundaries (`ibkr/`, `brokerage/`, main system):

### Layer 1: `ibkr/` — IBKR-Specific Futures Data

Things only IBKR knows how to do. Already partially built.

- **Contract qualification** — `resolve_futures_contract()` in `ibkr/contracts.py` (done)
- **Exchange routing metadata** — `ibkr/exchange_mappings.yaml` with exchange + currency per root symbol (done, 26 contracts)
- **FMP commodity symbol mapping** — `ibkr_futures_to_fmp` section in YAML (done)
- **Continuous contract data** — `IBKRMarketDataClient` with futures-aware duration handling (done)
- **Daily + monthly bars** — `fetch_monthly_close_futures()`, `fetch_daily_close_futures()` (done)
- **Contract multipliers + tick sizes** — needs to be added to `exchange_mappings.yaml` (Phase 1)

### Layer 2: `brokerage/futures/` — General Futures Domain Model

Broker-agnostic contract schema, notional math, and symbol resolution. New subpackage.

- **`FuturesContractSpec`** — dataclass: symbol, multiplier, tick_size, currency, exchange, asset_class, point_value
- **Notional calculation** — `quantity × multiplier × price`
- **Point value / P&L** — `price_change × multiplier × quantity`
- **Symbol resolution** — mapping between IBKR root, exchange product code, and FMP commodity symbol
- **Asset class taxonomy** — equity_index, fixed_income, metals, energy, agricultural (for risk grouping)

This is the "contract spec sheet" layer. If a second futures source were added (e.g., direct CME data), it would produce the same `FuturesContractSpec`.

### Layer 3: Main System — Integration + Analysis

Where futures data enters the portfolio view, risk engine, performance, and MCP tools.

- **Pricing chain** — dispatch futures tickers to IBKR/FMP commodity endpoints
- **Portfolio view** — futures as a separate exposure layer alongside equities
- **Risk decomposition** — macro/asset-class factors instead of equity factors
- **Performance attribution** — returns on notional, FX-adjusted
- **Trading analysis** — extend existing FIFO or separate futures trades view
- **MCP tools** — surface futures exposure in positions, risk, performance

## Key Design Decisions

### 1. Portfolio Value: Margin + Notional Overlay

Futures positions contribute to portfolio value in two ways:

- **Margin-based value**: The actual capital at risk (margin requirement). This contributes to total portfolio value and reflects realized gains/losses. This is what the brokerage reports as position value.
- **Notional overlay**: `quantity × multiplier × price` — the true economic exposure. Shown alongside equity exposure but NOT added to total portfolio value (would be misleading — 1 ES contract = ~$280k notional but only ~$15k margin).

In the portfolio view:
```
Total Portfolio Value: $130,000  (equities at market + futures at margin)
  Equity Exposure:    $130,000
  Futures Notional:   $280,000  (overlay, not added to total)
    ES ×2:            $280,000  (margin: $30,000)
```

### 2. Risk Analysis: Asset Class / Macro Factors

Futures don't have equity factor exposure (no industry, no stock-specific beta). Instead:

- **Equity index futures** (ES, NQ, NKD) → market beta, can be decomposed into sector/factor exposure of the underlying index
- **Fixed income futures** (ZB, ZN) → duration/rates exposure
- **Commodity futures** (GC, CL) → commodity factor exposure
- **Currency futures** → FX exposure

Initial implementation: treat futures as macro factor overlays with correlation to portfolio. Full factor decomposition is a later phase.

### 3. Performance Attribution

Futures returns are computed on notional value:
- `return = (price_end - price_start) / price_start`
- Adjusted for FX if non-USD settlement currency
- Roll P&L tracked separately when rolling between contract months

### 4. Trading Analysis

Two options (not mutually exclusive):
- **Integrated**: Futures trades flow through existing `TradingAnalyzer` FIFO matcher. Futures P&L = `price_change × multiplier × quantity`. Normalizers handle futures-specific fields.
- **Standalone**: Dedicated futures trade view with roll tracking, expiry awareness, and contract-specific P&L. Better for futures-specific analysis.

Start integrated (extend existing), add standalone view later if needed.

### 5. Symbol Resolution Chain

Futures have multiple symbol representations:
```
IBKR root:     ES
Exchange code:  ES (CME)
FMP commodity:  ESUSD
Display name:   E-mini S&P 500

IBKR root:     ESTX50
Exchange code:  FESX (EUREX)
FMP commodity:  ^STOXX50E
Display name:   Euro STOXX 50
```

The `brokerage/futures/` module owns the canonical mapping. IBKR-specific symbols stay in `ibkr/exchange_mappings.yaml`. The domain model resolves between them.

## Phased Implementation

### Phase 1: Data Foundation ✅
- Added multiplier + tick_size to `ibkr/exchange_mappings.yaml` (26 contracts)
- Created `brokerage/futures/` with `FuturesContractSpec`, notional/P&L math, asset class taxonomy
- `contracts.yaml` as canonical catalog (lru_cached via `load_contract_specs()`)
- Tests for contract specs, notional calculation, symbol resolution

### Phase 2: Pricing Dispatch ✅
- `latest_price()` and `get_returns_dataframe()` route futures via `instrument_types` → `FuturesPricingChain`
- FMP source (11/26 symbols) → IBKR fallback when TWS connected
- Currency auto-detected from contract spec (no manual `currency_map` for known futures)
- Z ticker collision guard (Zillow vs FTSE) via instrument_types check

### Phase 3: Portfolio Integration ✅
- `enrich_futures_positions()` shared helper adds notional/multiplier/asset_class/tick_size/tick_value
- Called from all 3 `PositionResult.from_dataframe()` sites + `refresh_portfolio_prices()`
- `get_exposure_snapshot()` returns `futures_exposure` section (contract_count, total_notional, by_asset_class)
- Position flags: `futures_notional` (info >0.5x) and `futures_high_notional` (warning >2x)

### Phase 4: Risk Integration ✅
- Notional-weighted risk decomposition (futures weighted by `contracts × multiplier × price`)
- Asset-class proxy factors: equity_index→SPY, metals→SPY+GLD, energy→SPY+USO
- Fixed income futures mapped to "bond" class for interest_rate factor eligibility
- Commodity factor as new factor key in both beta and factor-vol paths
- Segment view: `get_risk_analysis(segment="equities"|"futures"|"all")`
- FX attribution wired from `build_portfolio_view()` into `RiskAnalysisResult`
- `notional_leverage` threaded through full pipeline (standardize→config→analysis→result)
- Risk flags: `notional_leverage` (info >1.3x), `high_notional_leverage` (warning >2.0x)
- Plan: `docs/planning/FUTURES_P4_RISK_INTEGRATION_PLAN.md`

### Phase 5: Performance + Trading ✅
- `instrument_type`, `multiplier`, `contract_quantity` on OpenLot/ClosedTrade/IncompleteTrade/TradeResult
- `txn_meta` threading through all 12 FIFOMatcher call sites
- `futures_breakdown` in agent snapshot (futures vs equity P&L, win rate)
- `futures_trading_losses` + `futures_pnl_dominant` trading flags
- `segment` parameter on `get_trading_analysis()` (all/equities/futures)
- Top-level `multiplier` convenience field on IBKR Flex normalizer output
- No P&L math changes (IBKR pre-multiplies quantity, FIFO already correct)
- Hypothetical performance already works via pricing chain (Phase 2)
- Plans: `docs/planning/FUTURES_P5_PERFORMANCE_TRADING_PLAN.md`, `docs/planning/TRADING_SEGMENT_FILTER_PLAN.md`

### Phase 6: Monthly Contracts, Term Structure & Roll Execution ✅
Detailed plan: `docs/planning/FUTURES_MONTHLY_CURVE_ROLL_PLAN.md`
- Monthly contract resolution (`contract_month` param on `resolve_futures_contract()`, `fetch_futures_months()`)
- `get_futures_curve()` MCP tool — term structure across all active months, contango/backwardation detection, calendar spreads, annualized basis, close-price fallback for weekend/holiday data
- `preview_futures_roll()` / `execute_futures_roll()` MCP tools — atomic BAG combo orders (sell front + buy back)
- `IBKR_TRADE_CLIENT_ID` — dedicated client ID for the trading adapter to avoid collisions with ibkr-mcp
- Commits: `8ff76db9` (implementation), `63a948a0` (client_id fix)

### Phase 7: Contract Verification ✅
- Live-tested ESTX50 and DAX against TWS: contract resolution, qualification, monthly close data, pricing chain
- ESTX50: conId=621358639, EUREX/EUR, mult=10, FMP `^STOXX50E` works as primary source
- DAX: conId=621358482, EUREX/EUR, mult=25, FMP `^GDAXI` returns 402 → IBKR fallback
- IBV removed from catalog — no CME Ibovespa futures product found on IBKR (27→26 contracts)
- Verification runbook: `docs/reference/FUTURES_CONTRACT_VERIFICATION.md`

### Phase 8: Polish (Backlog)
- Daily bars → risk pipeline (requires frequency-aware refactor of 8+ annualization sites)
- Config-driven `instrument_types` from DB (currently YAML auto-detect only)

## Existing Infrastructure Summary

| Component | Status | Location |
|-----------|--------|----------|
| 26 contract definitions (exchange + currency) | Done | `ibkr/exchange_mappings.yaml` |
| FMP commodity symbol mapping (26 contracts) | Done | `ibkr/exchange_mappings.yaml` |
| Contract resolution (ContFuture) | Done | `ibkr/contracts.py` |
| Continuous contract data fetching | Done | `ibkr/market_data.py` |
| Futures-aware duration handling | Done | `ibkr/market_data.py` |
| `instrument_types` auto-detection | Done | `portfolio_risk_engine/data_objects.py` |
| `instrument_types` threading through config | Done | `core/config_adapters.py` |
| FX attribution decomposition | Done | `portfolio_risk.py` |
| `InstrumentType` enum (includes "futures") | Done | `trading_analysis/instrument_meta.py` |
| `contract_identity` dict on InstrumentMeta | Done | `trading_analysis/instrument_meta.py` |
| Contract multipliers + tick sizes | Done (Phase 1) | `brokerage/futures/contracts.yaml` |
| `FuturesContractSpec` domain model | Done (Phase 1) | `brokerage/futures/contract_spec.py` |
| Notional calculation | Done (Phase 1) | `brokerage/futures/math.py` |
| Pricing dispatch for futures | Done (Phase 2) | `brokerage/futures/pricing.py` |
| Currency auto-detection from contract spec | Done (Phase 2) | `portfolio_risk_engine/portfolio_config.py` |
| Portfolio value with margin vs notional | Done (Phase 3) | `services/position_enrichment.py` |
| Futures exposure snapshot | Done (Phase 3) | `core/result_objects/positions.py` |
| Notional-weighted risk decomposition | Done (Phase 4) | `portfolio_risk_engine/portfolio_config.py` |
| Asset-class proxy factors | Done (Phase 4) | `mcp_tools/risk.py` |
| Commodity factor | Done (Phase 4) | `portfolio_risk_engine/portfolio_risk.py` |
| Segment view (equities/futures/all) | Done (Phase 4) | `mcp_tools/risk.py` |
| FX attribution in RiskAnalysisResult | Done (Phase 4) | `core/result_objects/risk.py` |
| Notional leverage flags | Done (Phase 4) | `portfolio_risk_engine/risk_flags.py` |
| Futures metadata on FIFO trade objects | Done (Phase 5) | `trading_analysis/fifo_matcher.py` |
| Futures metadata on TradeResult | Done (Phase 5) | `trading_analysis/models.py` |
| Futures breakdown in agent snapshot | Done (Phase 5) | `trading_analysis/models.py` |
| Futures trading flags | Done (Phase 5) | `core/trading_flags.py` |
| Trading segment view (equities/futures/all) | Done (Phase 5) | `mcp_tools/trading_analysis.py` |
| Monthly contract resolution | Done (Phase 6) | `ibkr/contracts.py`, `ibkr/metadata.py` |
| Futures months discovery | Done (Phase 6) | `ibkr/metadata.py`, `ibkr/client.py`, `ibkr/compat.py` |
| Futures curve / term structure | Done (Phase 6) | `ibkr/market_data.py`, `mcp_tools/futures_curve.py`, `core/futures_curve_flags.py` |
| Futures roll preview + execution | Done (Phase 6) | `brokerage/ibkr/adapter.py`, `services/trade_execution_service.py`, `mcp_tools/futures_roll.py` |

## Package Boundary Rules

- `ibkr/` — IBKR-specific data and API calls. No imports from `brokerage/` or main system.
- `brokerage/futures/` — Broker-agnostic domain model. May import from `ibkr/compat.py` (public boundary) to load IBKR metadata. No imports from main system.
- Main system (`core/`, `services/`, `mcp_tools/`) — Imports from both `ibkr/compat.py` and `brokerage/futures/`. Owns the integration logic.
- `trading_analysis/` — Shared instrument types (`InstrumentMeta`). Both `brokerage/` and main system may import from here.
