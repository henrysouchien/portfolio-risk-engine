# Instrument Type × Provider Routing Audit

> **Date**: 2026-03-22
> **Status**: AUDIT COMPLETE
> **TODO ref**: `docs/TODO.md` line 63 ("Instrument Type × Provider Routing Audit")
> **Related**: Provider extensibility refactor (`d25f7b40`), `docs/planning/PROVIDER_EXTENSIBILITY_AUDIT.md`

---

## Executive Summary

9 instrument types flow through a tiered pricing system (FMP → IBKR → B-S), with exclusion sets for risk analysis and normalizer-driven classification. The routing is **mostly clean** with 8 identified gaps: CEF type disagreement across normalizers, bond pricing silent failure, non-IBKR option contract_identity gaps, legacy price loaders missing instrument_type passthrough, Plaid ISIN-only bond identity, "unknown" inconsistent treatment across pipelines, "unknown" positions vanishing silently, and crypto not classified.

---

## The InstrumentType Enum

Defined in `trading_analysis/instrument_meta.py`:

| Type | Description | Position type? |
|------|-------------|---------------|
| `equity` | Stocks, ETFs | Yes |
| `mutual_fund` | Mutual funds, CEFs | Yes |
| `option` | Equity options with contract identity | Yes |
| `futures` | Futures contracts | Yes |
| `bond` | Fixed income securities | Yes |
| `fx` | FX pairs (live pricing only) | No (excluded) |
| `fx_artifact` | Synthetic FX artifacts | No (excluded) |
| `income` | Dividend/interest rows | No (transaction-only) |
| `unknown` | Unclassifiable securities | No (excluded) |

**Exclusion set**: `_EXCLUDED_INSTRUMENT_TYPES = {"fx", "fx_artifact", "unknown"}` — these skip VaR, correlation, factor analysis, and realized performance.

---

## Complete Routing Matrix

### Pricing Provider Chain

Each instrument type flows through the `ProviderRegistry` price chain, sorted by priority (lower = tried first):

| Type | FMP (priority=10) | IBKR (priority=20) | B-S (priority=25) | Notes |
|------|-------------------|--------------------|--------------------|-------|
| **equity** | `can_price=True` | `can_price=False` | `can_price=False` | FMP only |
| **mutual_fund** | `can_price=True` (accepted directly) | `can_price=False` | `can_price=False` | FMP handles mutual_fund same as equities |
| **option** | `can_price=False` | `can_price=True` (needs contract_identity) | `can_price=True` (needs contract_identity) | IBKR primary, B-S fallback |
| **futures** | `can_price=True` (symbol mapped via `_resolve_futures_fmp_symbol`) | `can_price=True` | `can_price=False` | FMP commodity mapping (ES→^GSPC), IBKR fallback |
| **bond** | `can_price=False` | `can_price=True` (needs contract_identity) | `can_price=False` | IBKR only |
| **fx** | `can_price=False` | `can_price=True` | `can_price=False` | IBKR only (live) |
| **fx_artifact** | No provider | No provider | No provider | Excluded from all pricing |
| **income** | N/A | N/A | N/A | Transaction-only, never priced |
| **unknown** | No provider | No provider | No provider | Excluded from all pricing |

### Spot Price Path (`providers/price_service.py:get_spot_price()`)

| Type | Handler | Returns |
|------|---------|---------|
| `cash`, `option` | Hard skip (line 54-55) | `(None, None)` |
| `futures`, `derivative` | Futures pricing chain + FMP fallback (lines 57-75) | `(price, spec_currency)` |
| All others | `QuoteProvider.fetch_quote()` via registry (lines 77-91) | `(price, currency)` |

### Price Eligibility Filter (`providers/price_service.py:filter_price_eligible()`)

| Type | Included? | Notes |
|------|-----------|-------|
| `equity`, `mutual_fund`, `bond`, `cash` | Yes | Sent to batch pricing |
| `fx`, `fx_artifact`, `unknown` | Yes | NOT filtered — passes through (potential gap: these types hit QuoteProvider with no data) |
| `futures`, `option`, `derivative` | No | Filtered out (separate pricing path) |

**Note**: `filter_price_eligible()` only excludes `futures`, `option`, `derivative`. Types like `fx`, `fx_artifact`, `unknown` are NOT excluded by this filter — they pass through and hit the QuoteProvider, which will return empty results. The exclusion of these types happens upstream in `_EXCLUDED_INSTRUMENT_TYPES` for risk analysis, not in the pricing filter.

### Risk Analysis Treatment

| Type | VaR/Correlation | Factor Analysis | Proxy Builder | Realized Perf |
|------|-----------------|-----------------|---------------|---------------|
| **equity** | Included | Full factor exposure | FMP profile for sector/industry | Included |
| **mutual_fund** | Included | Full factor exposure | FMP profile | Included |
| **option** | Conditional (`OPTION_PRICING_PORTFOLIO_ENABLED`) | Excluded from proxy | Skip FMP profile | Conditional (`OPTION_MULTIPLIER_NAV_ENABLED`) |
| **futures** | Included (with FX adjust) | Excluded from proxy | Skip FMP profile | Included (margin-based capital) |
| **bond** | Included | Full factor exposure | FMP profile (but no bond-specific data) | Included |
| **fx** | Excluded | Excluded | Excluded | Excluded |
| **fx_artifact** | Excluded | Excluded | Excluded | Excluded |
| **income** | N/A | N/A | N/A | N/A |
| **unknown** | Excluded | Excluded | Excluded | Excluded |

### Normalizer Classification

| Normalizer | equity | option | futures | bond | mutual_fund | fx_artifact | unknown |
|-----------|--------|--------|---------|------|-------------|-------------|---------|
| **IBKR Flex** | Default | `is_option` flag | `is_futures` flag | — | — | — | — |
| **Plaid** | Default | Regex/keyword | Futures type | Fixed income flag | Mutual fund type | FX pair detection | UNKNOWN prefix |
| **SnapTrade** | `cs,ps,ad,ut,wi,et` codes | `op,opt` codes | `fut,future` codes | `bnd,bond` codes | `oef` code | FX pair detection | Unknown prefix |
| **Schwab** | `EQUITY` type | `OPTION` type | — | `FIXED_INCOME` type | `MUTUAL_FUND` type | — | — |

**Known disagreement**: SnapTrade classifies CEFs (e.g., DSU) as `equity`, Plaid classifies them as `mutual_fund`. Noted in `services/security_type_service.py`. SnapTrade maps `cef` → `equity` in its type code table; Plaid detects closed-end funds via security metadata and assigns `mutual_fund`.

### Feature Flags

| Flag | Default | Controls |
|------|---------|----------|
| `OPTION_BS_FALLBACK_ENABLED` | false | Registers B-S provider at priority=25 |
| `OPTION_PRICING_PORTFOLIO_ENABLED` | false | Routes options through price chain in portfolio analysis |
| `OPTION_MULTIPLIER_NAV_ENABLED` | false | Applies ×100 multiplier for non-IBKR option cash flows |
| `EXERCISE_COST_BASIS_ENABLED` | false | Links option exercises to underlying stock cost basis |

No feature flags for equity, futures, bond, or mutual_fund pricing — those are always-on.

---

## Audit Questions & Answers

### Q1: Full matrix — instrument type × pricing provider × normalizer × analysis path × risk treatment

See tables above. 9 types × 5 dimensions fully mapped.

### Q2: Silent fall-through to wrong providers?

**Yes, 2 cases:**

1. **`mutual_fund` → FMP equity endpoint**: FMP's `can_price()` accepts `mutual_fund` directly and calls the same `fetch_monthly_close` as equities. Works in practice (FMP treats mutual funds and equities identically on the `/historical-price-full` endpoint) but not explicitly validated. If a mutual fund ticker doesn't exist in FMP's equity universe, it silently returns empty Series.

2. **`bond` → `filter_price_eligible()` includes bonds**: Bonds pass the filter and are sent to batch FMP quote fetches. But FMP has no bond pricing data — these calls return stale/no data. Only IBKR with `contract_identity` provides real bond prices.

### Q3: Option IBKR → B-S fallback chain clean?

**Mostly clean, one gap:**
- IBKR → B-S works when `OPTION_BS_FALLBACK_ENABLED=true` AND full `contract_identity` dict present (needs `underlying`, `right`, `strike`, `expiry`).
- **Gap**: Non-IBKR options (from Schwab, SnapTrade, Plaid normalizers) may have incomplete `contract_identity`. If `underlying` or `expiry` missing, B-S returns empty Series silently. No warning surfaced.

### Q4: Futures — 27 contracts routing correctly?

**Yes, clean.** 27 contracts in `ibkr/exchange_mappings.yaml`. FMP symbol mapping (`ES` → `^GSPC`, `NQ` → `^NDX`, etc.) handles commodity index proxies. IBKR fallback for contracts FMP can't map. FX adjustment for non-USD futures (GBP, EUR, JPY, HKD). Margin-based capital anchor for realized performance.

### Q5: Bond CUSIP resolution?

**Limited.** IBKR bond pricing requires `contract_identity` dict with CUSIP-derived fields. Non-IBKR bonds (from Plaid `fixed_income` flag, Schwab `FIXED_INCOME` type) typically lack `contract_identity`. These bonds get included in risk analysis (not excluded) but have no historical returns → appear as zero-return positions. No CUSIP resolution fallback exists.

### Q6: Crypto?

**Not handled.** No `crypto` value in `InstrumentType` enum. FMP has crypto endpoints (`/crypto/list`, `/quote/<symbol>`) but no instrument type routing points to them. Crypto positions would classify as `equity` (if ticker matches FMP) or `unknown` (if not). No explicit crypto detection in any normalizer.

### Q7: Cash/money market properly excluded?

**Yes, clean.** Cash exclusion happens at multiple levels:
- `portfolio_risk_engine/portfolio_risk.py` filters cash from analysis weights
- `core/proxy_builder.py` skips cash for proxy mapping
- `SecurityTypeService` detects cash proxies (SGOV, ERNS.L, IBGE.L) via hardcoded list
- `get_spot_price()` returns `(None, None)` for cash
- Cash positions retained for portfolio value but excluded from risk/factor calculations

### Q8: SecurityTypeService vs normalizer agreement?

**Mostly aligned, one known disagreement:**
- SecurityTypeService provides a 5-tier classification (cash proxy → DB cache → FMP industry → security type mapping → AI fallback) that supplements but does not override normalizer assignments.
- **Disagreement**: CEFs (e.g., DSU). SnapTrade normalizer → `equity` (maps `cef` code to equity). Plaid normalizer → `mutual_fund` (detects via security metadata). SecurityTypeService uses FMP profile as tiebreaker, but the normalizer assignment is what flows into `instrument_type` on the position.
- **Impact**: DSU gets different stress test scenarios depending on which brokerage data source is used.

### Q9: Feature flags — should any gates be removed?

| Flag | Recommendation |
|------|---------------|
| `OPTION_BS_FALLBACK_ENABLED` | Keep gated — B-S assumptions may not suit all option structures |
| `OPTION_PRICING_PORTFOLIO_ENABLED` | Consider enabling — mature enough for production |
| `OPTION_MULTIPLIER_NAV_ENABLED` | Consider enabling — fixes real cash flow bug for non-IBKR options |
| `EXERCISE_COST_BASIS_ENABLED` | Keep gated — limited to IBKR Flex `code` field parsing |

---

## Identified Gaps (Prioritized)

| # | Gap | Severity | Impact | Fix |
|---|-----|----------|--------|-----|
| 1 | **CEF type disagreement** — SnapTrade=equity, Plaid=mutual_fund for same position (e.g., DSU) | Medium | Different stress scenarios, inconsistent risk treatment across sources | Normalize CEFs: either add `cef` to InstrumentType or enforce one classification across all normalizers |
| 2 | **Bond pricing silent failure** — included in filter_price_eligible but FMP has no bond data | Medium | Bonds without IBKR contract_identity get zero historical returns | Add bond warning in agent-format flags; exclude bonds from FMP batch pricing |
| 3 | **Non-IBKR option contract_identity gaps** — Schwab/SnapTrade/Plaid options may lack full contract_identity | Medium | B-S fallback returns empty Series, no pricing for these options | Audit contract_identity completeness per normalizer |
| 4 | **Legacy price loaders missing instrument_type** — `portfolio_risk_engine/providers.py:58` defaults missing `instrument_type` to `equity`; callers like `portfolio_config.py:303` and `portfolio_risk.py:718` don't pass instrument_type | Medium | Bonds/FX can silently route through FMP equity path | Thread `instrument_type` through all price loader call sites |
| 5 | **Plaid bond ISIN-only contract_identity** — Plaid emits `contract_identity` with only `isin` (`providers/normalizers/plaid.py:192`), but IBKR bond resolver only honors `con_id` or `cusip` (`ibkr/contracts.py:129`) | Medium | ISIN-only bonds still won't price via IBKR | Add ISIN→CUSIP resolution or accept ISIN in bond resolver |
| 6 | **"unknown" treatment inconsistent** — excluded from realized perf (`engine.py:273`) but trading analysis remaps `unknown` → `equity` before price lookup (`analyzer.py:1134`) | Low-Medium | Same position gets different treatment in different pipelines | Align exclusion behavior or add explicit remap documentation |
| 7 | **"unknown" positions vanish silently** — excluded from analysis with no user warning | Low-Medium | User doesn't know positions are being ignored | Surface "excluded positions" warning in position flags |
| 8 | **Crypto not classified** — no InstrumentType, no routing | Low | Crypto positions get wrong risk treatment (equity or unknown) | Add `crypto` to enum + FMP crypto route (when users have crypto) |

---

## Key Files

| File | Role |
|------|------|
| `trading_analysis/instrument_meta.py` | InstrumentType enum, `_EXCLUDED_INSTRUMENT_TYPES` |
| `providers/registry.py` | ProviderRegistry, `get_price_chain()` |
| `providers/fmp_price.py` | FMPProvider `can_price()` — equity, etf, fund, futures |
| `providers/ibkr_price.py` | IBKRPriceProvider `can_price()` — futures, fx, bond, option |
| `providers/bs_option_price.py` | OptionBSPriceProvider `can_price()` — option only |
| `providers/price_service.py` | `get_spot_price()`, `filter_price_eligible()` |
| `providers/normalizers/` | 4 normalizers (plaid, snaptrade, ibkr_flex, schwab) |
| `portfolio_risk_engine/portfolio_risk.py` | Risk analysis routing per instrument type |
| `core/proxy_builder.py` | Proxy skip logic for non-equities |
| `core/realized_performance/engine.py` | Exclusion set, option multiplier |
| `services/security_type_service.py` | 5-tier classification (supplements normalizers) |
| `settings.py` | Feature flags |
