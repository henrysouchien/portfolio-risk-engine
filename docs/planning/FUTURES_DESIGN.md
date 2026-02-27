# Futures Portfolio Integration — High-Level Design

## Overview

Futures are fundamentally different from equities in pricing, sizing, symbols, currency, and risk decomposition — but they are part of the same portfolio and must integrate into holdings, performance, risk analysis, and trading views.

This document outlines the architecture for futures support: what stays separate, what integrates, and how the pieces connect.

## Architecture: Three-Layer Split

Following existing package boundaries (`ibkr/`, `brokerage/`, main system):

### Layer 1: `ibkr/` — IBKR-Specific Futures Data

Things only IBKR knows how to do. Already partially built.

- **Contract qualification** — `resolve_futures_contract()` in `ibkr/contracts.py` (done)
- **Exchange routing metadata** — `ibkr/exchange_mappings.yaml` with exchange + currency per root symbol (done, 27 contracts)
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

### Phase 1: Data Foundation (brokerage domain model + IBKR metadata)
- Add multiplier + tick_size to `ibkr/exchange_mappings.yaml`
- Create `brokerage/futures/` with `FuturesContractSpec` and notional math
- Wire contract specs through `contract_identity` in existing `InstrumentMeta`
- Tests for contract specs, notional calculation, symbol resolution

### Phase 2: Pricing Dispatch
- Modify pricing chain (`latest_price()`, `get_returns_dataframe()`) to route futures tickers
- Consult `instrument_types` to dispatch to IBKR/FMP commodity endpoints
- Auto-detect currency from contract spec (eliminate manual `currency_map` for known futures)
- Handle the Z ticker collision (Zillow equity vs FTSE futures) via instrument_types guard

### Phase 3: Portfolio Integration
- Futures positions in holdings view with notional + margin columns
- Total portfolio value = equities at market + futures at margin value
- Notional exposure shown as overlay
- MCP `get_positions()` extended with futures exposure section

### Phase 4: Risk Integration
- Futures contribute to portfolio risk via asset-class correlation
- Equity index futures decomposed into market beta
- Fixed income / commodity futures as separate risk factors
- FX attribution for non-USD futures (already built, needs wiring)
- Wire `fx_attribution` into `RiskAnalysisResult` (currently only in `build_portfolio_view()` output)

### Phase 5: Performance + Trading
- Futures performance attribution on notional returns
- Trading analysis extended with futures P&L (multiplier-aware)
- Roll tracking and expiry awareness (if holding physical contracts vs continuous)

### Phase 6: Polish
- Daily bars → risk pipeline (currently monthly only)
- Config-driven `instrument_types` from DB (currently YAML auto-detect only)
- IBKR contract verification for remaining symbols (IBV, ESTX50, DAX)
- Standalone futures trading view (if needed beyond integrated)

## Existing Infrastructure Summary

| Component | Status | Location |
|-----------|--------|----------|
| 27 contract definitions (exchange + currency) | Done | `ibkr/exchange_mappings.yaml` |
| FMP commodity symbol mapping (27 contracts) | Done | `ibkr/exchange_mappings.yaml` |
| Contract resolution (ContFuture) | Done | `ibkr/contracts.py` |
| Continuous contract data fetching | Done | `ibkr/market_data.py` |
| Futures-aware duration handling | Done | `ibkr/market_data.py` |
| `instrument_types` auto-detection | Done | `portfolio_risk_engine/data_objects.py` |
| `instrument_types` threading through config | Done | `core/config_adapters.py` |
| FX attribution decomposition | Done | `portfolio_risk.py` |
| `InstrumentType` enum (includes "futures") | Done | `trading_analysis/instrument_meta.py` |
| `contract_identity` dict on InstrumentMeta | Done | `trading_analysis/instrument_meta.py` |
| Contract multipliers | **Missing** | — |
| Tick sizes | **Missing** | — |
| `FuturesContractSpec` domain model | **Missing** | — |
| Notional calculation | **Missing** | — |
| Pricing dispatch for futures | **Missing** | — |
| Currency auto-detection from contract spec | **Missing** | — |
| Portfolio value with margin vs notional | **Missing** | — |
| Macro factor risk decomposition | **Missing** | — |

## Package Boundary Rules

- `ibkr/` — IBKR-specific data and API calls. No imports from `brokerage/` or main system.
- `brokerage/futures/` — Broker-agnostic domain model. May import from `ibkr/compat.py` (public boundary) to load IBKR metadata. No imports from main system.
- Main system (`core/`, `services/`, `mcp_tools/`) — Imports from both `ibkr/compat.py` and `brokerage/futures/`. Owns the integration logic.
- `trading_analysis/` — Shared instrument types (`InstrumentMeta`). Both `brokerage/` and main system may import from here.
