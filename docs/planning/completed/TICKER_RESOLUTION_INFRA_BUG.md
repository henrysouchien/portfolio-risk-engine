# Bug: Raw→FMP Ticker Mapping Lost in Realized Performance Pipeline

## Status: COMPLETE

## Problem

International tickers from Plaid/SnapTrade use raw provider symbols (e.g., `AT.` for Ashtead Group) that differ from FMP-compatible symbols (`AT.L`). The `resolve_fmp_ticker()` function correctly resolves these during position sync, but the mapping is lost by the time the realized performance pipeline needs it.

## Root Cause

1. **Position sync** (Plaid/SnapTrade loaders): `resolve_fmp_ticker()` is called and stores `fmp_ticker="AT.L"` on the position record alongside `ticker="AT."`
2. **Consolidation**: Merges positions across providers — `AT.` (Plaid) and `AT.L` (SnapTrade) become one consolidated position with canonical ticker `AT.L`
3. **`_build_current_positions()`** (`core/realized_performance_analysis.py:107`): Builds `fmp_ticker_map` from consolidated positions only → gets `{"AT.L": "AT.L"}` but **not** `{"AT.": "AT.L"}`
4. **`fifo_transactions`**: Historical Plaid transactions retain the raw `AT.` symbol (the trading analyzer uses raw provider tickers, not resolved FMP tickers)
5. **Price fetch**: `fetch_monthly_close("AT.")` has no mapping → FMP receives raw `AT.` → HTTP 402

Result: `AT.` and `AT.L` appear as separate positions in the position timeline. `AT.` can't be priced.

## Scope

Affects any international ticker where:
- The raw provider symbol differs from the FMP symbol (e.g., `AT.` vs `AT.L`, or any ticker needing exchange suffix)
- The ticker appears in `fifo_transactions` (historical trades)
- The raw→FMP mapping isn't preserved through consolidation

Currently known: `AT.` (Ashtead Group, LSE). Likely affects other London/international stocks if traded historically through Plaid.

## Upstream Issue: Provider Normalization

### Current state (inconsistent)

`fetch_all_transactions()` in `trading_analysis/data_fetcher.py` pulls transactions from ALL providers regardless of which provider "owns" which brokerage account:

```
fetch_all_transactions():
  → fetch_snaptrade_activities()    # ALL SnapTrade accounts
  → fetch_plaid_transactions()      # ALL Plaid accounts (including IBKR)
  → fetch_ibkr_flex_trades()        # IBKR direct
```

This creates redundant data: IBKR trades appear from both Plaid AND IBKR Flex. Dedup handles the overlap, but raw Plaid ticker variants (e.g., `AT.`) still leak into `fifo_transactions`.

### Desired state (normalized)

Each brokerage account should have ONE canonical provider for both positions and transactions:

| Account | Positions | Transactions | Notes |
|---------|-----------|-------------|-------|
| IBKR | SnapTrade | IBKR Flex | Plaid IBKR data is redundant |
| Merrill | Plaid | Plaid | SnapTrade doesn't support Merrill |
| Others | SnapTrade | SnapTrade | |

This means:
- **Stop pulling IBKR transactions from Plaid** — IBKR Flex provides better data (multipliers, asset categories, open/close indicators, futures support)
- **Keep Plaid transactions for Merrill** — only source for Merrill trade history
- **Keep SnapTrade transactions for SnapTrade-connected accounts**

### Implementation approach

Option 1: **Filter at fetch time** — `fetch_plaid_transactions()` skips IBKR-connected Plaid accounts (detect via institution name). Simple but hardcoded.

Option 2: **Provider routing config** — A config mapping `{institution → {positions: provider, transactions: provider}}` that controls which provider is used for each account. More flexible, supports future providers.

Option 3: **Filter at analyzer level** — `TradingAnalyzer` drops Plaid transactions with `_institution` matching IBKR when `ibkr_flex_trades` are present. Already partially done by dedup, but this would be a hard filter rather than dedup-based cleanup.

## Fix Options (for raw→FMP mapping)

### Option A: Preserve raw→FMP mappings before consolidation
- In `_build_current_positions()`, access pre-consolidation position data to capture all raw→FMP mappings
- Requires threading pre-consolidation data through the pipeline
- Most complete fix but touches position infrastructure

### Option B: Build ticker normalization map from fifo_transactions
- In `analyze_realized_performance()`, scan `fifo_transactions` for tickers with known exchange patterns (e.g., ending in `.`) and resolve them via `resolve_fmp_ticker()` or exchange_mappings
- Self-contained fix within realized performance pipeline
- Adds FMP API calls during analysis

### Option C: Normalize tickers in TradingAnalyzer at ingestion
- Call `resolve_fmp_ticker()` when building `fifo_transactions` in the analyzer
- Fixes at the source — all downstream code sees FMP-compatible tickers
- Adds new dependency (FMP resolution) to the trading analyzer
- May be slow (API calls per ticker)

### Option D: Use `fmp_ticker_map` in `build_position_timeline()` to normalize keys
- The function already accepts `fmp_ticker_map` but ignores it (deletes it at line 178)
- Use it to normalize position_timeline keys from raw to FMP-compatible
- Clean but still requires `fmp_ticker_map` to contain the raw→FMP mapping (back to Option A)

## Priority

Low-medium. The ticker resolution bug currently only affects `AT.` — the position is priced correctly via the `AT.L` path, the `AT.` variant just adds noise. Provider normalization is a cleaner long-term fix that also eliminates redundant data fetching and dedup overhead.
