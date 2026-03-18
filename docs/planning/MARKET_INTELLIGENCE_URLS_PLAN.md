# Plan: Add clickable URLs to Market Intelligence news events

**Status:** Codex review FAIL → v2 (addressing sanitization + test coverage)

## Context

The Market Intelligence banner on the Overview dashboard shows portfolio-relevant events (news, earnings, dividends, etc.). The FMP news API already returns a `url` field for every article, but `build_market_events()` drops it. This plan threads the URL through the full stack so news/sentiment events render as clickable links.

**Scope:** Only news/sentiment events get URLs — the other 5 event types (earnings, economic, dividends, estimate revisions, insider trades) don't have URLs in their FMP data sources.

## Steps

### Step 1 — Backend: pass sanitized `url` through in `_build_news_events()`

**File:** `mcp_tools/news_events.py` (~line 390-401)

Add URL extraction with scheme validation — only allow `http:`/`https:` URLs, strip whitespace, reject `javascript:`/`data:`/empty strings:

```python
raw_url = (article.get("url") or "").strip()
safe_url = raw_url if raw_url.startswith(("https://", "http://")) else None

source_events.append(
    {
        "type": "sentiment",
        ...
        "ticker": ticker or None,
        "url": safe_url,
    }
)
```

### Step 2 — Frontend types: add `url?: string`

**File 1:** `frontend/packages/chassis/src/catalog/types.ts` (line ~486)
Add `url?: string;` to `MarketEventSourceItem`.

**File 2:** `frontend/packages/ui/src/components/portfolio/overview/types.ts` (line ~34)
Add `url?: string;` to `MarketEvent`.

**File 3:** `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` (line ~4)
Add `url?: string;` to local `MarketEvent` interface (duplicate type that would otherwise drift).

(`MarketEventItem` in connectors is derived from `MarketEventSourceItem` via `SDKSourceOutputMap`, so it inherits automatically.)

### Step 3 — Frontend transformer: map the `url` field

**File:** `frontend/packages/connectors/src/resolver/registry.ts` (line ~106)

Add to `transformMarketEvents`:
```typescript
url: event.url ? String(event.url) : undefined,
```

### Step 4 — Frontend component: render clickable link

**File:** `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx` (line ~52)

Import `ExternalLink` from `lucide-react`. Wrap the description text: if `event.url` exists, render as `<a href={event.url} target="_blank" rel="noopener noreferrer">` with subtle styling (text color inherited, underline on hover, small ExternalLink icon inline). If no URL, render plain `<p>` as before.

### Step 5 — Tests

**File 1:** `tests/mcp_tools/test_news_events_builder.py`
- Add test: news event includes `url` field when article has valid URL
- Add test: `url` is `None` when article URL is empty/missing/non-http scheme

**File 2:** `tests/api/test_positions_market_intelligence.py`
- Add test: API response includes `url` on sentiment events

**File 3:** `frontend/packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx`
- Add test: `url` field passes through transformer

**File 4:** `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.test.tsx` (new)
- Test: event with `url` renders an `<a>` with `target="_blank"`, `rel="noopener noreferrer"`, and ExternalLink icon
- Test: event without `url` renders plain `<p>` text with no link
- Follow sibling test pattern (vitest + @testing-library/react, mock lucide-react icons)

## Files modified

| File | Change |
|------|--------|
| `mcp_tools/news_events.py` | Add sanitized `"url"` to news event dict |
| `frontend/packages/chassis/src/catalog/types.ts` | Add `url?: string` to `MarketEventSourceItem` |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | Add `url?: string` to `MarketEvent` |
| `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` | Add `url?: string` to local `MarketEvent` |
| `frontend/packages/connectors/src/resolver/registry.ts` | Map `url` field in `transformMarketEvents` |
| `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx` | Render clickable link + ExternalLink icon |
| `tests/mcp_tools/test_news_events_builder.py` | URL passthrough + sanitization tests |
| `tests/api/test_positions_market_intelligence.py` | API response URL test |
| `frontend/packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx` | Transformer URL test |
| `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.test.tsx` | Anchor rendering + plain text fallback tests (new) |

## Verification

1. Run backend tests: `pytest tests/mcp_tools/test_news_events_builder.py tests/api/test_positions_market_intelligence.py -x`
2. Run frontend tests: `cd frontend && npx vitest run --reporter=verbose`
3. Check TypeScript compiles: `cd frontend && npx tsc --noEmit`
4. Visual check: news events in the banner should show clickable links that open in a new tab
