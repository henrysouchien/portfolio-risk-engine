# Plan: Rename `relevance` → `portfolioRelevance` in Market Intelligence

## Context
The `relevance` field on market intelligence events is actually a **portfolio-weighted** score (based on position weight), not an intrinsic stock relevance metric. Renaming to `portfolioRelevance` makes the semantics clear at every layer. UI label changes from "70% relevant" to "70% portfolio relevance".

## Changes

### Step 1: Backend — `mcp_tools/news_events.py`
- Rename all `"relevance"` dict keys to `"portfolioRelevance"` in event construction (~6 event source blocks)
- Rename local variable `relevance` to `portfolio_relevance` for clarity
- Update sort keys: `event.get("relevance", 0)` → `event.get("portfolioRelevance", 0)` (4 sort sites)
- Update `actionRequired` threshold check from `relevance > 60` to `portfolio_relevance > 60`
- Update docstring at `_load_portfolio_weights()`

### Step 2: Frontend types — 3 files
- `packages/chassis/src/catalog/types.ts` line 381: `relevance` → `portfolioRelevance` in `MarketEventSourceItem`
- `packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` line 8: `relevance` → `portfolioRelevance` in `MarketEvent`
- `packages/ui/src/components/portfolio/overview/types.ts` line 29: `relevance` → `portfolioRelevance` in `MarketEvent`

### Step 3: Frontend transformer — `packages/connectors/src/resolver/registry.ts`
- Line 95: `relevance: Number(event.relevance ?? 0)` → `portfolioRelevance: Number(event.portfolioRelevance ?? 0)`

### Step 4: Frontend component — `packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx`
- Line 49: `{event.relevance}% relevant` → `{event.portfolioRelevance}% portfolio relevance`

### Step 5: Backend tests
- `tests/mcp_tools/test_news_events_builder.py`: Update all `["relevance"]` assertions to `["portfolioRelevance"]` (~6 sites)
- `tests/api/test_positions_market_intelligence.py`: Update test payload field name

### Step 6: Frontend tests
- `packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx`: Update test data + assertions (~2 sites)

## Files touched (9)
1. `mcp_tools/news_events.py`
2. `frontend/packages/chassis/src/catalog/types.ts`
3. `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts`
4. `frontend/packages/connectors/src/resolver/registry.ts`
5. `frontend/packages/ui/src/components/portfolio/overview/types.ts`
6. `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx`
7. `tests/mcp_tools/test_news_events_builder.py`
8. `tests/api/test_positions_market_intelligence.py`
9. `frontend/packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx`

Note: `routes/positions.py` passes through events dict as-is — no change needed.

## Verification
1. `python3 -m pytest tests/mcp_tools/test_news_events_builder.py tests/mcp_tools/test_news_events_portfolio.py tests/api/test_positions_market_intelligence.py -q`
2. `cd frontend && npx vitest run packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx`
3. Live test: reload dashboard, scroll to Market Intelligence banner, confirm label reads "XX% portfolio relevance"
