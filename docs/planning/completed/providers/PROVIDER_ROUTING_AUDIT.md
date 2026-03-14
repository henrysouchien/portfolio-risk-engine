# Provider Routing Architecture Audit

**Date:** 2026-03-03
**Status:** Findings documented, no changes made

## Overview

Audit of provider routing consistency across positions, transactions, trading, and pricing. The architecture is **clean and well-separated** overall — findings below are minor gaps, not structural issues.

---

## 1. Provider Coverage Matrix

| Provider | Positions | Transactions | Trading | Pricing |
|----------|-----------|-------------|---------|---------|
| **Plaid** | Yes | Yes (skipped when direct available) | No (read-only) | — |
| **SnapTrade** | Yes | Yes (skipped when direct available) | Yes (default adapter) | — |
| **Schwab** | Yes (direct) | Yes (direct) | Yes (adapter) | — |
| **IBKR Flex** | No | Yes (direct) | — | — |
| **IBKR** | — | — | Yes (adapter, client_id=22) | Fallback (priority=20) |
| **FMP** | — | — | — | Primary (priority=10) |

## 2. Routing Architecture

### Positions & Transactions
- Centralized in `providers/routing_config.py` with three tables: `POSITION_ROUTING`, `TRANSACTION_ROUTING`, `TRADE_ROUTING`
- Institution slug aliases (`INSTITUTION_SLUG_ALIASES`) resolve consistently across all paths
- Core routing logic in `providers/routing.py`: `resolve_providers_for_institution()`, `resolve_provider_token()`, `institution_belongs_to_provider()`
- Positions orchestrated by `services/position_service.py`, transactions by `trading_analysis/data_fetcher.py`
- Transactions use "direct-first" fetch policy — direct providers (ibkr_flex, schwab) run first, aggregators skip institutions that already have direct data

### Pricing
Three intentionally separate paths:
1. **Modern Registry** (`providers/registry.py`): FMP (priority=10) → IBKR (priority=20) — equities, bonds, options, FX
2. **Legacy Adapter** (`portfolio_risk_engine/providers.py`): `_RegistryBackedPriceProvider` bridges old callers to registry
3. **Futures Chain** (`brokerage/futures/pricing.py`): FMP → IBKR, commodity-focused, intentionally decoupled

### Trading Execution
- MCP tools → `TradeExecutionService` → `_resolve_broker_adapter(account_id)` → adapter
- Adapter selection: TRADE_ROUTING + TRADE_ACCOUNT_MAP → `owns_account()` → DB fallback
- IBKR uses dedicated singleton connection (client_id=22, separate from data client_id=20/21)

### Package Boundaries

| Package | Role | Status |
|---------|------|--------|
| `ibkr/` | Read-only data facade | Clean — 36 callers via `compat.py` |
| `brokerage/ibkr/adapter.py` | Trade execution only | Clean — no data imports |
| `providers/fmp_price.py` | FMP pricing (priority=10) | Clean |
| `providers/ibkr_price.py` | IBKR pricing fallback (priority=20) | Clean |
| `brokerage/futures/pricing.py` | Futures chain (separate) | Clean |

---

## 3. Findings

### Finding 1: No IBKR Direct Position Provider
**Severity:** Low (works today, minor inefficiency)

Positions for IBKR accounts come via aggregators (Plaid/SnapTrade), while transactions come via ibkr_flex (direct). This means two different data sources for the same institution. Consolidation handles dedup, but the asymmetry means IBKR position data depends on aggregator availability.

`POSITION_ROUTING` only has `charles_schwab → schwab`. No `interactive_brokers` entry.

**Action:** Consider adding IBKR position provider (wrapping `IBKRClient.get_positions()`). Low priority — aggregators work fine.

### Finding 2: Positions Lack Direct-First Optimization
**Severity:** Low (extra fetches, no incorrect data)

Transactions use `direct_first` fetch policy — direct providers run first, aggregators skip institutions with healthy direct coverage. Positions fetch all enabled providers equally, so Schwab users get both Plaid + Schwab position data (consolidation deduplicates, but extra API calls).

**Action:** Add direct-first logic to `position_service.py` mirroring `data_fetcher.py`. Low priority — position fetches are fast and cached.

### Finding 3: Ephemeral IBKR Mode Breaks `owns_account()`
**Severity:** Low (production has `IBKR_AUTHORIZED_ACCOUNTS` set)

When `IBKR_AUTHORIZED_ACCOUNTS` is empty, `IBKRBrokerAdapter.owns_account()` always returns False. Falls back to DB-based `_detect_account_provider()` which requires pre-existing position history. New accounts can't trade until they appear in positions table.

**Action:** Document limitation in adapter docstring. No code change needed — production config has authorized accounts.

### Finding 4: Account Filtering Asymmetry
**Severity:** Low

`get_all_positions()` supports `account` filter parameter. `fetch_transactions_for_source()` does not. Account scoping for transactions currently happens at the MCP tool layer (post-fetch filtering).

**Action:** Add `account` filter to transaction fetcher for consistency. Low priority — MCP-level filtering works.

### Finding 5: Transaction Provider Missing Availability Check
**Severity:** Very Low

Position providers check both `is_provider_enabled()` and `is_provider_available()`. Transaction providers only check `is_provider_enabled()`. Missing availability check could cause fetch-time failures for providers that are enabled but not configured.

**Action:** Add `is_provider_available()` check to transaction provider registration in `data_fetcher.py`.

### Finding 6: Account Alias Resolution Inconsistency
**Severity:** Very Low

`IBKRBrokerAdapter._resolve_native_account()` uses simple `TRADE_ACCOUNT_MAP.get()` lookup. `basket_trading.py` uses `resolve_account_aliases()` which builds equivalence classes. Both work for current 1:1 mappings, but semantics differ if n:n mappings were ever needed.

**Action:** Clarify intent with comment. Current 1:1 usage is fine.

---

## 4. Key Files

| File | Role |
|------|------|
| `providers/routing.py` | Core routing logic + enablement |
| `providers/routing_config.py` | Routing tables + institution mappings |
| `providers/registry.py` | Price provider registry |
| `providers/bootstrap.py` | Registry builder + singleton |
| `providers/fmp_price.py` | FMP pricing provider |
| `providers/ibkr_price.py` | IBKR pricing provider |
| `services/position_service.py` | Position fetch orchestration |
| `trading_analysis/data_fetcher.py` | Transaction fetch orchestration |
| `services/trade_execution_service.py` | Trade execution routing |
| `brokerage/ibkr/adapter.py` | IBKR trade adapter |
| `ibkr/compat.py` | IBKR public interface |
| `brokerage/futures/pricing.py` | Futures pricing chain |
| `portfolio_risk_engine/providers.py` | Legacy price provider adapter |
