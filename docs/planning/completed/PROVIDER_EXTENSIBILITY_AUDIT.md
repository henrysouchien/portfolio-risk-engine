# Provider Extensibility Architecture Audit

> **Date**: 2026-03-20
> **Status**: AUDIT COMPLETE — DECOUPLING IMPLEMENTED
> **Implementation plan**: `docs/planning/PROVIDER_EXTENSIBILITY_PLAN.md` (implemented 2026-03-20)
> **TODO ref**: `docs/TODO.md` lines 43-59 ("Data Provider Extensibility & Resale")

---

## Executive Summary

The provider abstraction layer (6 Protocol classes, priority-ordered `ProviderRegistry`) is **well-designed and truly generic**. But ~60% of live data calls bypass the registry entirely — 18+ production files create `FMPClient()` inline for spot prices, quotes, profiles, currency inference, sector mapping, and ticker resolution. A new provider plugged into the registry would only see ~40% of data requests.

The frontend is **fully provider-agnostic** (zero FMP references). All decoupling work is backend-only.

**Bottom line**: Adding a new price provider to the registry chain takes ~2 days. Making the codebase actually use it everywhere takes ~3 weeks. Tiers 1-2 (~9 days) deliver 80% of the value.

---

## Audit Questions & Answers

### Q1: How much work to add a new price provider today?

**Moderate for the price chain (~2 days), large for full parity (~3 weeks).**

The happy path works well:
1. Create `providers/polygon_price.py` implementing `PriceSeriesProvider` protocol
2. Register in `providers/bootstrap.py` with a priority (e.g., `priority=15`)
3. Optionally gate with `POLYGON_ENABLED` env var

The new provider gets called for `fetch_monthly_close` / `fetch_daily_close` through the registry chain. Three existing providers demonstrate the pattern: `FMPProvider` (195 lines), `IBKRPriceProvider`, `OptionBSPriceProvider`.

**But the registry only covers ~40% of live data calls.** The remaining 60% bypass it:

- `get_spot_price()` in `providers/price_service.py:86` calls `fetch_fmp_quote_with_currency()` directly for equities
- `proxy_builder.py:345` makes raw HTTP to `financialmodelingprep.com/stable/profile`
- `mcp_tools/trading_helpers.py:33` creates `FMPClient()` inline for live prices
- `mcp_tools/quote.py:36` creates `FMPClient()` for the `get_quote` MCP tool
- `portfolio_risk_engine/_ticker.py:17,97` creates `FMPClient()` for currency inference
- See full bypass map in Q3 below

### Q2: Can providers be hot-swapped via config?

**No. No mechanism exists.**

Evidence:
- `providers/bootstrap.py` hardcodes FMP at priority=10, IBKR at priority=20, B-S at priority=25
- No env var controls which price providers load or their ordering
- `OPTION_BS_FALLBACK_ENABLED` is the only price-provider env var (binary on/off for B-S)
- Brokerage providers have `ENABLED_PROVIDERS`, `DEFAULT_POSITION_PROVIDERS`, `DEFAULT_TRANSACTION_PROVIDERS` — but no equivalent `PRICE_PROVIDERS` or `PRICE_PROVIDER_STACK` exists
- `FXProvider` / `CurrencyResolver` in `portfolio_risk_engine/providers.py` default to `FMPFXProvider` / `FMPCurrencyResolver` with no config override

**What "hot-swap via config" would require:**
- `PRICE_PROVIDERS=polygon,fmp,ibkr` env var parsed in `bootstrap.py`
- Provider factory pattern (name → class mapping)
- Config-driven priority system
- Currently none of this exists

### Q3: What's FMP-specific vs generic?

**Protocol layer: fully generic (A grade).** 6 Protocol classes in `providers/interfaces.py` have zero FMP assumptions:

| Protocol | Methods | Implementations |
|----------|---------|----------------|
| `PriceSeriesProvider` | `can_price()`, `fetch_monthly_close()`, `fetch_daily_close()` | FMPProvider, IBKRPriceProvider, OptionBSPriceProvider |
| `TreasuryRateProvider` | `fetch_monthly_treasury_rates()` | FMPProvider |
| `DividendProvider` | `fetch_monthly_total_return_price()`, `fetch_dividend_history()`, `fetch_current_dividend_yield()` | FMPProvider |
| `PositionProvider` | `fetch_positions()` | (brokerage providers) |
| `TransactionProvider` | `fetch_transactions()` | (brokerage providers) |
| `TransactionNormalizer` | `normalize(raw_data, security_lookup=None)` | 5 normalizers (snaptrade, plaid, ibkr_flex, ibkr_statement, schwab) |

**Implementation layer: ~60% direct coupling.** Full bypass map:

#### Category A — FMP Adapter/Boundary Code (5 files, OK)

These files implement or manage the FMP edge of the abstraction — they don't "go through" the registry, but their coupling is architectural (adapter pattern or cache management).

| File | Import | Why OK |
|------|--------|--------|
| `providers/fmp_price.py` | `fmp.compat.*` | IS the FMP protocol adapter — its job to wrap FMP behind `PriceSeriesProvider` |
| `portfolio_risk_engine/_fmp_provider.py` | `fmp.compat.*`, `fmp.fx.*` | Legacy FMP adapter behind `PriceProvider`/`FXProvider` protocols |
| `core/realized_performance/pricing.py` | `fmp.compat.fetch_daily_close` | Builds its own local registry (FMP=10, IBKR=20, BS=25 — duplicates `bootstrap.py` priorities) |
| `services/cache_adapters.py` | `fmp.compat.*`, `fmp.cache.*` | Cache management — FMP caches need FMP-specific clear/stats |
| `portfolio_risk_engine/factor_utils.py` | `fmp.cache.get_timeseries_store` | Disk cache for peer median series; pricing goes through provider-backed loader |

**Note**: `core/realized_performance/pricing.py:86-102` duplicates the hardcoded priority stack from `bootstrap.py`. Any config-driven provider changes must update both files.

#### Category B — Direct FMP Bypass (18 files, PROBLEMATIC)

| # | Severity | File | Call site(s) | What it does |
|---|----------|------|-------------|-------------|
| 1 | **CRITICAL** | `core/proxy_builder.py` | 303, 345 | Raw HTTP to `financialmodelingprep.com/stable/profile` with `FMP_API_KEY`. Only raw HTTP bypass in codebase. |
| 2 | **HIGH** | `portfolio_risk_engine/_ticker.py` | 17 (call), 97 (call) | `FMPClient().fetch_raw("profile")` for currency inference. `@lru_cache`. Import at 15. |
| 3 | **HIGH** | `portfolio_risk_engine/portfolio_risk.py` | 2278, 2280 | `FMPClient()` for sector mapping in `build_factor_return_contribution_by_sector()`. |
| 4 | **MEDIUM** | `portfolio_risk_engine/performance_metrics_engine.py` | 21 (import), 326 (call) | Direct `fmp.compat.fetch_daily_close` — but only feeds `compute_recent_returns()`, not core monthly metrics. |
| 5 | **HIGH** | `utils/ticker_resolver.py` | 19 (import), 49+ (calls) | Global `FMPClient` singleton for search, resolution, batch profiles, batch quotes. |
| 6 | **HIGH** | `providers/price_service.py` | 86 | `get_spot_price()` calls `fetch_fmp_quote_with_currency()` directly for equities. |
| 7 | **HIGH** | `mcp_tools/quote.py` | 36 | `FMPClient()` for `get_quote` MCP tool. |
| 8 | **HIGH** | `mcp_tools/trading_helpers.py` | 33 | `FMPClient()` for `fetch_current_prices()` (rebalance, trade generation). |
| 9 | **HIGH** | `mcp_tools/baskets.py` | 507+ | Multiple `FMPClient()` for ticker validation and pricing. |
| 10 | **HIGH** | `mcp_tools/basket_trading.py` | 305 | `FMPClient()` for trade pricing. |
| 11 | **HIGH** | `trading_analysis/analyzer.py` | 439 | `_get_fmp_client().fetch_raw("profile")` for company name in position key reconciliation. |
| 12 | **HIGH** | `services/stock_service.py` | 110 (init), 223, 335, 352, 377, 412 | `self.fmp_client` (lazy `get_client()`) for search, profile, quote enrichment — generic operations, not just FMP-native analytics. |
| 13 | **MEDIUM** | `services/agent_building_blocks.py` | 547, 567 | `FMPClient()` for stock metadata inference. |
| 14 | **MEDIUM** | `services/portfolio_service.py` | 1560, 1734, 1757, 1897 | `FMPClient()` for performance enrichment, quote, historical price. |
| 15 | **MEDIUM** | `services/position_service.py` | 1532, 1543 | FMP helper calls for position-level enrichment. |
| 16 | **MEDIUM** | `mcp_tools/income.py` | 247 (call) | `get_client()` for dividend data. Import at 234. |
| 17 | **MEDIUM** | `mcp_tools/factor_intelligence.py` | 106 (call) | `FMPClient()` for factor group series. Import at 79. |
| 18 | **LOW** | `mcp_tools/news_events.py` | 12-16 | Direct imports from `fmp.tools.*` (estimates, core). |

#### Category C — FMP-Native Features (intentional coupling, no generic equivalent)

These sites remain intentionally coupled to FMP after the provider extensibility refactor. They use FMP-specific analytical endpoints with no generic protocol equivalent. Abstracting them only makes sense if an alternative provider offers equivalent features.

| File | What | Notes |
|------|------|-------|
| `mcp_tools/news_events.py` | News, estimates, insider, calendar | Imports `fmp.tools.*` directly. Reclassified from Category B — these are FMP-native features, not generic data calls. |
| `mcp_tools/__init__.py` | Re-exports FMP screening, peers, news, technical, transcripts | FMP analytical features exposed as MCP tools |
| `services/stock_service.py` | ratios_ttm, historical_price_adjusted, peers, technical | FMP-native analytical endpoints (generic search/profile/quote routed through registry in Step 11) |
| `services/agent_building_blocks.py:fetch_fmp_data` | Generic FMP endpoint passthrough | Intentional — this IS the FMP proxy tool |
| `services/portfolio_service.py:1757,1917,1930,1943` | historical_price_eod, price_target_consensus, analyst endpoints | FMP-native analytical data |
| `mcp_tools/income.py` | dividends_calendar endpoint | FMP-specific calendar format |
| `mcp_tools/baskets.py:1053` | etf_holdings endpoint | FMP-native ETF holdings data |
| `portfolio_risk_engine/factor_utils.py` | `fmp.cache.get_timeseries_store` | FMP disk cache for peer median series |

#### Raw `FMP_API_KEY` references outside `fmp/`

- `core/proxy_builder.py:303` — raw HTTP
- `portfolio_risk_engine/factor_utils.py:53-55` — **dead code** (declared but unused)
- `portfolio_risk_engine/portfolio_risk.py:2275` — gates sector fetch
- `portfolio_risk_engine/config.py:118,153` — config defaults
- `mcp_server.py:58` — startup validation

### Q4: Frontend assumptions?

**None. The frontend is fully provider-agnostic.**

Evidence:
- Zero `fmp` or `FMP` or `financialmodelingprep` string matches in any `.ts` or `.tsx` file
- Response shapes use generic financial metrics: `peRatio`, `sharpeRatio`, `beta`, `marketCap` — standard names, not FMP field names
- All adapters use defensive extraction with type guards (`?.`, `|| 0`, fallback defaults)
- Backend owns all provider routing — frontend never selects or references a data provider
- `ProviderRoutingService.ts` is for brokerage connection flow (SnapTrade vs Plaid), not market data
- **Zero frontend work needed for provider extensibility**

---

## Extensibility Scorecard

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Protocol design | **A** | 6 clean Protocols, `runtime_checkable`, no FMP assumptions |
| Registry mechanics | **A-** | Priority chain works; no config-driven stack selection |
| Price chain (monthly close) | **B+** | Works through registry for historical prices |
| Spot price / quotes | **D** | `get_spot_price()` and `get_quote()` hardcode FMP |
| Profile / metadata | **F** | Raw HTTP in proxy_builder, global FMPClient singleton in ticker_resolver |
| FX / currency | **C** | `FXProvider` protocol exists, defaults to FMP, no alternative impl |
| Config-driven swapping | **F** | No mechanism exists |
| Frontend coupling | **A+** | Zero FMP references anywhere |
| **Overall** | **C-** | Protocol layer excellent but bypassed ~60% of the time (18 files) |

---

## Prioritized Decoupling Backlog

### Tier 1 — Foundation (new protocols + worst offenders) ~6 days

| # | Change | Key Files | Size |
|---|--------|-----------|------|
| 1 | Add 3 new protocols: `ProfileMetadataProvider`, `QuoteProvider`, `SymbolSearchProvider` + registry slots | `providers/interfaces.py`, `providers/registry.py`, `providers/bootstrap.py` | M |
| 2 | Create FMP implementations of all 3 new protocols | New: `providers/fmp_metadata.py` | M |
| 3 | Route `proxy_builder.py` profile fetch through registry (eliminate raw HTTP) | `core/proxy_builder.py` | S |
| 4 | Route `_ticker.py` currency/quote through registry | `portfolio_risk_engine/_ticker.py` | M |
| 5 | Route `get_spot_price()` through `QuoteProvider`; rename `filter_fmp_eligible()` → `filter_price_eligible()` | `providers/price_service.py` | M |

### Tier 2 — Core engine decoupling ~5 days

| # | Change | Key Files | Size |
|---|--------|-----------|------|
| 6 | Route `performance_metrics_engine.py` daily close through registry | `portfolio_risk_engine/performance_metrics_engine.py` | S |
| 7 | Route `portfolio_risk.py` sector mapping through `ProfileMetadataProvider` | `portfolio_risk_engine/portfolio_risk.py` | M |
| 8 | Add config-driven price provider stack (`PRICE_PROVIDERS` env var + factory pattern). Must cover **both** `providers/bootstrap.py` AND `core/realized_performance/pricing.py` (duplicated priority stack at lines 86-102) | `providers/bootstrap.py`, `core/realized_performance/pricing.py`, `settings.py` | M |
| 9 | Route `trading_analysis/analyzer.py` company name lookup through `ProfileMetadataProvider` | `trading_analysis/analyzer.py` | S |
| 10 | Clean dead `FMP_API_KEY` / `BASE_URL` constants | `portfolio_risk_engine/factor_utils.py` | S |

### Tier 3 — Service layer decoupling (app-facing, high priority) ~6 days

Moved ahead of MCP tools — these are app-facing via REST routes.

| # | Change | Key Files | Size |
|---|--------|-----------|------|
| 11 | Route `services/stock_service.py` search/profile/quote through registry (6 generic FMP call sites) | `services/stock_service.py` | L |
| 12 | Route `services/portfolio_service.py` enrichment through registry (5 FMP call sites) | `services/portfolio_service.py` | M |
| 13 | Route `services/position_service.py` enrichment through registry | `services/position_service.py` | M |
| 14 | Route `services/agent_building_blocks.py` through registry | `services/agent_building_blocks.py` | M |
| 15 | Route `utils/ticker_resolver.py` through registry (hardest — global singleton, central to ticker resolution) | `utils/ticker_resolver.py` | L |

### Tier 4 — MCP tool decoupling ~5 days

| # | Change | Key Files | Size |
|---|--------|-----------|------|
| 16 | Route `mcp_tools/quote.py` through `QuoteProvider` | `mcp_tools/quote.py` | S |
| 17 | Route `mcp_tools/trading_helpers.py` through registry | `mcp_tools/trading_helpers.py` | S |
| 18 | Route `mcp_tools/baskets.py` through registry (5+ FMPClient sites) | `mcp_tools/baskets.py` | M |
| 19 | Route `mcp_tools/basket_trading.py` through registry | `mcp_tools/basket_trading.py` | S |
| 20 | Route `mcp_tools/income.py` dividend fetch through `DividendProvider` | `mcp_tools/income.py` | M |
| 21 | Route `mcp_tools/factor_intelligence.py` through registry | `mcp_tools/factor_intelligence.py` | S |

### Tier 5 — FMP-native features (document intentional coupling)

| # | Change | Key Files | Size |
|---|--------|-----------|------|
| 22 | Assess + document FMP-native tools (news, screening, peers, technical, transcripts, estimates) | `mcp_tools/news_events.py`, `mcp_tools/__init__.py`, `services/stock_service.py` (analytics portion) | L |

### Effort Summary

| Tier | Items | Effort | Outcome |
|------|-------|--------|---------|
| Tier 1 | 5 | ~6 days | 3 new protocols. Worst offenders (raw HTTP, currency, spot price) routed through registry. |
| Tier 2 | 5 | ~5 days | Core engine fully decoupled. Config-driven provider stack (both bootstrap sites). |
| Tier 3 | 5 | ~6 days | All service layer uses registry. Stock service + ticker resolver are hardest. |
| Tier 4 | 6 | ~5 days | All MCP tools use registry. |
| Tier 5 | 1 | ~3 days | Document intentional FMP coupling for analytical features. |
| **Total** | **22** | **~4 weeks** | Full provider-agnostic codebase. `PRICE_PROVIDER=polygon` just works. |

**Tiers 1-2 alone (~11 days) deliver 80% of value** — core pricing/metadata/quotes fully abstracted, config-driven swapping works for the primary analysis pipeline.

---

## Key Files Reference

**Provider infrastructure (well-designed):**
- `providers/interfaces.py` — 6 Protocol classes
- `providers/registry.py` — `ProviderRegistry` (priority-ordered price chain)
- `providers/bootstrap.py` — `build_default_registry()`, `get_registry()` singleton
- `providers/fmp_price.py` — `FMPProvider` (PriceSeriesProvider + TreasuryRateProvider + DividendProvider)
- `providers/ibkr_price.py` — `IBKRPriceProvider` (futures, FX, bonds, options)
- `providers/bs_option_price.py` — `OptionBSPriceProvider` (B-S fallback)
- `providers/price_service.py` — `get_spot_price()`, `filter_fmp_eligible()`
- `providers/routing.py` — Institution routing, provider enablement
- `providers/symbol_resolution.py` — `SymbolResolver`

**Worst bypass offenders (fix first):**
- `core/proxy_builder.py` — Raw HTTP to FMP (CRITICAL)
- `portfolio_risk_engine/_ticker.py` — Currency inference bypass (HIGH)
- `utils/ticker_resolver.py` — Global FMPClient singleton (HIGH, hardest to fix)
- `providers/price_service.py` — Spot price bypass (HIGH)
