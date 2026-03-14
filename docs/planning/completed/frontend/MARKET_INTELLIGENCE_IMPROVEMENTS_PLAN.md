# Market Intelligence Improvements

**Status**: PLAN
**Issue**: TODO #11 — Market Intelligence relevance scoring + action items
**Scope**: Backend (`mcp_tools/news_events.py`) + frontend type updates (4 files: add `"dividend"` to `MarketEvent.type` union, add `ticker?: string`, fix `transformMarketEvents()` to pass through `ticker`).

---

## Current State

`build_market_events()` in `mcp_tools/news_events.py` produces a `MarketEvent[]` from two sources:
1. **News** → `type: "sentiment"`, relevance from portfolio weight, keyword-based impact
2. **Earnings calendar** → `type: "earnings"`, relevance from portfolio weight

Frontend `MarketEvent.type` union: `"earnings" | "fed" | "economic" | "geopolitical" | "technical" | "sentiment"` — only `sentiment` and `earnings` are populated today.

## Gaps

1. **Economic calendar missing** — CPI, Fed rate decisions, jobs reports, etc. affect the whole portfolio but aren't shown. FMP's `get_economic_data(mode="calendar")` returns events with an `impact` field (High/Medium/Low).
2. **Dividend events missing** — Portfolio dividends/splits calendar exists (`_PORTFOLIO_CALENDAR_TYPES` includes them) but `build_market_events()` only queries earnings.
3. **Action items are just a boolean** — `actionRequired: True` with no guidance. For large positions near earnings or ex-dividend dates, a brief recommendation would be more useful.
4. **Estimate revision signals missing** — `screen_estimate_revisions()` in `fmp/tools/estimates.py` accepts a ticker list and returns EPS/revenue revision direction. Analyst estimate momentum is a leading indicator.
5. **Insider trade signals missing** — `get_insider_trades()` in `fmp/tools/insider.py` returns recent insider buy/sell activity. Meaningful for large holdings where insiders are selling.

## Changes

### Step 1: Economic calendar events

Add a new section to `build_market_events()` that queries `get_economic_data(mode="calendar")` for High-impact US events in the next 7 days.

**File**: `mcp_tools/news_events.py`

**New import**: `from fmp.tools.market import get_economic_data`

**New constants**:
```python
# FMP impact levels that warrant surfacing to users (case-insensitive check below).
_HIGH_IMPACT_ECON = {"high"}

# Economic event keywords that map to type "fed" instead of "economic".
_FED_KEYWORDS = {"fed", "fomc", "federal funds", "interest rate decision"}

# Position types considered individual equities (for estimate revision + insider trade filtering).
_EQUITY_TYPES = {"equity", "stock"}
```

**New block in `build_market_events()`** (after earnings, before sort):
```python
# --- Economic calendar events ---
try:
    today = datetime.now().strftime("%Y-%m-%d")
    econ_to = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    econ_result = get_economic_data(
        mode="calendar",
        from_date=today,
        to_date=econ_to,
        country="US",
        format="full",
        use_cache=use_cache,
    )
    if econ_result.get("status") == "success":
        # Sort by date ascending (nearest first), with Fed events prioritized
        # on same-day ties so CPI doesn't shadow FOMC
        def _econ_sort_key(r):
            # Use day-only token for sorting (matches dedup granularity)
            # so Fed events always win same-day ties regardless of timestamp ordering
            date_day = (r.get("date") or "").split(" ")[0]
            name = (r.get("event") or "").lower()
            is_fed = any(k in name for k in _FED_KEYWORDS)
            return (date_day, 0 if is_fed else 1)

        econ_data = sorted(
            econ_result.get("data", []),
            key=_econ_sort_key,
        )
        econ_count = 0
        for row in econ_data:
            if econ_count >= 3:
                break
            if (row.get("impact") or "").lower() not in _HIGH_IMPACT_ECON:
                continue
            event_name = row.get("event", "")
            event_date = (row.get("date") or "").split(" ")[0]

            event_lower = event_name.lower()
            event_type = "fed" if any(k in event_lower for k in _FED_KEYWORDS) else "economic"

            desc = event_name
            prev = row.get("previous")
            est = row.get("estimate")
            unit = row.get("unit") or ""
            if est is not None and prev is not None:
                desc += f" (est: {est}{unit}, prev: {prev}{unit})"
            elif est is not None:
                desc += f" (est: {est}{unit})"

            events.append({
                "type": event_type,
                "impact": "neutral",
                "description": desc,
                "relevance": 70,
                "timeframe": (row.get("date") or "Upcoming").split(" ")[0],
                "actionRequired": False,
            })
            econ_count += 1
except Exception:
    pass
```

**Budget**: max 3 economic events, capped by `econ_count`. No date-based dedup — distinct same-day events (e.g., FOMC + jobs report) are genuinely different catalysts and should both surface. The `econ_count <= 3` cap is sufficient to prevent flooding. Fed events sort first on same-day ties via the sort key.

**Rationale**: Economic events don't have a ticker or portfolio weight, so they get a fixed relevance of 70. They don't set `actionRequired` — they're awareness items.

### Step 2: Dividend events

Add a section querying `get_portfolio_events_calendar(event_type="dividends")` for upcoming ex-dividend dates on portfolio holdings.

**File**: `mcp_tools/news_events.py`

**New block in `build_market_events()`** (after economic, before sort):
```python
# --- Dividend calendar events ---
try:
    today = datetime.now().strftime("%Y-%m-%d")
    div_to = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    div_result = get_portfolio_events_calendar(
        user_email=user_email,
        event_type="dividends",
        from_date=today,
        to_date=div_to,
        account=account,
        use_cache=use_cache,
    )
    if div_result.get("status") == "success":
        div_count = 0
        for evt in div_result.get("events", []):
            if div_count >= 3:
                break
            ticker = (evt.get("symbol") or "").upper()
            weight = ticker_weights.get(ticker, 0)
            if not ticker or weight == 0:
                continue  # skip non-portfolio symbols (autofill leakage)

            relevance = min(90, max(15, int(weight * 200 + 25)))

            div_amount = evt.get("dividend")
            desc = f"{ticker} ex-dividend on {evt.get('date', 'upcoming')}"
            if div_amount:
                desc += f" (${div_amount}/share)"

            action = weight > 0.05
            if action:
                desc += f" — Review position ahead of ex-date ({weight:.0%} of portfolio)"

            events.append({
                "type": "dividend",
                "impact": "neutral",
                "description": desc,
                "relevance": relevance,
                "timeframe": evt.get("date", "Upcoming"),
                "actionRequired": action,
                "ticker": ticker or None,
            })
            div_count += 1
except Exception:
    pass
```

**Frontend type updates**: Add `"dividend"` to the `MarketEvent.type` union and add `ticker?: string` (already emitted by existing events but not declared). Changes in 4 files (all confirmed to have duplicate `MarketEvent` definitions):
- `frontend/packages/ui/src/components/portfolio/overview/types.ts` — add `"dividend"` to type union, add `ticker?: string`
- `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` (line 4) — add `"dividend"` to type union, add `ticker?: string`
- `frontend/packages/chassis/src/catalog/types.ts` (line 377) — add `"dividend"` to type union, add `ticker?: string`
- `frontend/packages/connectors/src/resolver/registry.ts` (line 90) — add `ticker` to `transformMarketEvents()` return object (currently stripped)

The `MarketIntelligenceBanner.tsx` renders `event.type.toUpperCase()` as the badge label (line 41), so it will automatically display "DIVIDEND" — no rendering logic change needed.

Note: `ticker` is already emitted by existing news and earnings events (lines 315, 349 of `news_events.py`) but was never declared in the TypeScript type. This change formalizes the existing contract.

### Step 3: Refactor `_load_portfolio_weights()` for position type awareness

**Prerequisite for Steps 4 and 5** — both estimate revisions and insider trades need to filter by position type (equity vs ETF/fund). This step changes the return type to carry position type alongside weight.

**File**: `mcp_tools/news_events.py`

**Change return type** from `dict[str, float]` to `dict[str, tuple[float, str]]` — each value becomes `(weight, position_type)`. This lets callers filter by type.

Current callers of `_load_portfolio_weights()`:
- `has_market_intelligence_data()` — uses `bool(weights)`, just needs `bool()` check (unaffected)
- `build_market_events()` — news/earnings/dividend blocks use `ticker_weights.get(ticker, 0)` for relevance scoring

**Migration**: Update callers to unpack the tuple at the top of `build_market_events()`:
```python
# In build_market_events(), after loading:
ticker_weights_raw = _load_portfolio_weights(...)
ticker_weights = {t: w for t, (w, _) in ticker_weights_raw.items()}
ticker_types = {t: ptype for t, (_, ptype) in ticker_weights_raw.items()}
```

This keeps `ticker_weights` as `dict[str, float]` for all existing relevance calculations, while `ticker_types` is available for Steps 4 and 5.

**Change in `_load_portfolio_weights()`** (line 228-229):
```python
# Before:
weights[fmp_ticker] = weights.get(fmp_ticker, 0) + weight
# After:
existing_weight, existing_type = weights.get(fmp_ticker, (0, ""))
# Prefer "equity"/"stock" type when merging — if any position for this
# ticker is an equity, treat it as equity (conservative for insider filtering).
merged_type = existing_type if existing_type in ("equity", "stock") else ptype
weights[fmp_ticker] = (existing_weight + weight, merged_type)
```

**Collision note**: Same fmp_ticker appearing as both "equity" and "etf" is rare (would require a ticker collision after FMP resolution). The precedence rule is: if any position is "equity"/"stock", the merged type is equity. This is conservative — it allows the insider check to run, and if it's actually an ETF the insider API returns empty data which is handled gracefully.

### Step 4: Estimate revision signals (depends on Step 3)

Query `screen_estimate_revisions()` with equity portfolio tickers to find stocks where analyst estimates are being revised up or down. This is a leading indicator — estimate momentum often precedes price moves.

**File**: `mcp_tools/news_events.py`

**New import**: `from fmp.tools.estimates import screen_estimate_revisions`

**New block in `build_market_events()`** (after dividends, before sort):
```python
# --- Estimate revision signals ---
try:
    # Only screen equities — estimate revisions are not meaningful for ETFs/funds.
    equity_tickers = [t for t in ticker_weights
                      if ticker_types.get(t, "") in _EQUITY_TYPES]
    if equity_tickers:
        rev_result = screen_estimate_revisions(
            tickers=equity_tickers,
            days=30,
            direction="all",
            period="quarter",
        )
        if rev_result.get("status") == "success":
            # Re-rank by portfolio-weighted impact: weight * abs(delta).
            # The API returns results sorted by abs(eps_delta), but a small
            # delta on a large holding matters more than a large delta on a tiny one.
            # Use eps_delta when available, fall back to revenue_delta (matching
            # the API's own fallback at estimates.py:227). Use explicit `is not None`
            # checks — `eps_delta=0.0` is a valid value (no change) and should NOT
            # fall through to revenue_delta.
            raw_revisions = rev_result.get("results", [])
            for rev in raw_revisions:
                t = (rev.get("ticker") or "").upper()
                w = ticker_weights.get(t, 0)
                eps_d = rev.get("eps_delta")
                rev_d = rev.get("revenue_delta")
                delta = eps_d if eps_d is not None else (rev_d if rev_d is not None else 0)
                rev["_portfolio_impact"] = w * abs(delta)
            raw_revisions.sort(key=lambda r: r.get("_portfolio_impact", 0), reverse=True)

            rev_count = 0
            for rev in raw_revisions:
                if rev_count >= 2:
                    break
                ticker = (rev.get("ticker") or "").upper()
                direction = rev.get("direction", "")
                if direction not in ("up", "down"):
                    continue  # skip flat/unknown — only surface clear momentum
                eps_delta = rev.get("eps_delta")
                weight = ticker_weights.get(ticker, 0)
                if weight < 0.02:
                    continue  # skip tiny positions

                relevance = min(90, max(25, int(weight * 250 + 30)))
                impact = "positive" if direction == "up" else "negative" if direction == "down" else "neutral"

                desc = f"{ticker} analyst estimates revised {direction}"
                if eps_delta is not None:
                    desc += f" (EPS Δ {eps_delta:+.2f})"
                if direction == "down" and weight > 0.05:
                    desc += f" — Review {ticker} thesis ({weight:.0%} of portfolio)"

                events.append({
                    "type": "sentiment",
                    "impact": impact,
                    "description": desc,
                    "relevance": relevance,
                    "timeframe": "Last 30 days",
                    "actionRequired": direction == "down" and weight > 0.05,
                    "ticker": ticker,
                })
                rev_count += 1
except Exception:
    pass
```

**Budget**: max 2 estimate revision events. Only surfaces positions > 2% weight to avoid noise. Results are re-ranked by `weight * abs(eps_delta)` (portfolio-weighted impact) so that a large holding with a moderate revision outranks a tiny holding with a large one. The API returns sorted by `abs(eps_delta)` alone, which would miss high-weight holdings with smaller deltas.

**Action logic**: Downward revisions on positions > 5% of portfolio trigger `actionRequired` with a "Review thesis" prompt. Upward revisions are informational only.

**Performance note**: `screen_estimate_revisions()` makes one HTTP call to the hosted estimates API with the full ticker list — no per-ticker looping. Typical response time is < 1s.

### Step 5: Insider trade signals (depends on Step 3)

Loop over top holdings and check for recent insider activity. Focus on significant insider selling in large positions as a warning signal.

**File**: `mcp_tools/news_events.py`

**New import**: `from fmp.tools.insider import get_insider_trades`

**Depends on**: Step 3 (`ticker_types` and `_EQUITY_TYPES` from `_load_portfolio_weights()` refactor).

**FMP response shape** (from `get_insider_trades(format="summary")`):
```python
{
    "status": "success",
    "recent_trades": [
        {"date": "2026-02-15", "insider": "John Doe", "title": "CFO",
         "type": "sell", "shares": 10000, "price": 150.0, "value": 1500000.0},
        {"date": "2026-02-10", "insider": "Jane Smith", "title": "CEO",
         "type": "buy", "shares": 5000, "price": 148.0, "value": 740000.0},
    ],
    "statistics": {...},  # lifetime aggregates — NOT used (see rationale below)
}
```

**Rationale**: `statistics.totalBuys`/`totalSells` are lifetime aggregates with no date window — stale historical selling can be misrepresented as a current signal. Instead, count buy/sell from `recent_trades` (which are date-stamped and sorted by recency) within a 90-day lookback. The `type` field is already normalized to `"buy"` / `"sell"` by `_normalize_trade_type()`.

**New constant**:
```python
_INSIDER_LOOKBACK_DAYS = 90
```

**New block in `build_market_events()`** (after estimates, before sort):
```python
# --- Insider trade signals ---
try:
    # Only check top 3 equity holdings to limit FMP API calls (2 FMP calls per symbol).
    # Filter out ETFs/funds — insider trades are only meaningful for individual stocks.
    equity_holdings = {t: w for t, w in ticker_weights.items()
                       if ticker_types.get(t, "") in _EQUITY_TYPES}
    top_holdings = sorted(equity_holdings.items(), key=lambda x: x[1], reverse=True)[:3]
    insider_count = 0
    cutoff = (datetime.now() - timedelta(days=_INSIDER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    for ticker, weight in top_holdings:
        if insider_count >= 2:
            break
        if weight < 0.03:
            continue

        # Use limit=100 to capture the full 90-day window for most stocks.
        # Very few equities have >100 insider filings in 90 days.
        insider_result = get_insider_trades(symbol=ticker, limit=100, format="summary", use_cache=use_cache)
        if insider_result.get("status") != "success":
            continue

        # Count recent buy/sell from date-stamped trades, not lifetime stats.
        recent_trades = insider_result.get("recent_trades", [])
        recent_buys = 0
        recent_sells = 0
        for trade in recent_trades:
            trade_date = trade.get("date", "")
            if trade_date < cutoff:
                break  # trades are sorted descending by date — stop at cutoff
            if trade.get("type") == "sell":
                recent_sells += 1
            elif trade.get("type") == "buy":
                recent_buys += 1

        if recent_sells == 0 or recent_sells <= recent_buys:
            continue  # no recent selling or net buying — not a warning signal

        relevance = min(90, max(30, int(weight * 200 + 35)))

        desc = f"{ticker} insider selling ({recent_sells} sell vs {recent_buys} buy in last {_INSIDER_LOOKBACK_DAYS}d)"
        if weight > 0.05:
            desc += f" — Monitor {ticker} ({weight:.0%} of portfolio)"

        # Use most recent trade date as timeframe
        most_recent_date = recent_trades[0].get("date", "Recent") if recent_trades else "Recent"

        events.append({
            "type": "sentiment",
            "impact": "negative",
            "description": desc,
            "relevance": relevance,
            "timeframe": f"As of {most_recent_date}",
            "actionRequired": weight > 0.05,
            "ticker": ticker,
        })
        insider_count += 1
except Exception:
    pass
```

**Budget**: max 2 insider events. Only checks top 3 equity holdings by weight. Only surfaces when `recent_sells > recent_buys` within a 90-day lookback window, using date-stamped `recent_trades` (not lifetime `statistics`).

**Performance note**: `get_insider_trades()` internally fetches both `insider_trades_search` and `insider_trade_statistics` endpoints per symbol (2 FMP calls each, parallelized internally). Top 3 holdings = up to 6 FMP calls total. Each call is fast (< 500ms), but total adds ~1.5s in worst case (internal parallelization per symbol). The `use_cache=True` default mitigates repeat calls. Acceptable given `build_market_events()` is called at page load, not on every interaction.

### Step 6: Enriched action descriptions

Currently `actionRequired` is a bare boolean. Enrich the `description` field for actionable items with a brief recommendation suffix.

**Changes in the news section** (existing block, lines ~308-316):
```python
desc = article.get("title", "")
if relevance > 60 and ticker:
    desc += f" — Review {ticker} position ({weight:.0%} of portfolio)"
```

**Changes in the earnings section** (existing block, lines ~333-349):

Add zero-weight guard (same pattern as dividend block) to prevent non-portfolio earnings from leaking through when autofill returns unfiltered calendar items. Iterate the full list with a counter — do NOT pre-truncate with `[:4]`, as leakage rows would waste slots:
```python
earn_count = 0
for evt in earnings_result.get("events", []):
    if earn_count >= 4:
        break
    ticker = (evt.get("symbol") or "").upper()
    weight = ticker_weights.get(ticker, 0)
    if not ticker or weight == 0:
        continue  # skip non-portfolio symbols (autofill leakage)

    relevance = min(95, max(20, int(weight * 300 + 30)))
    desc = f"{ticker} earnings report on {evt.get('date', 'upcoming')}"
    if evt.get("eps_estimated") is not None:
        desc += f" (EPS est: ${evt['eps_estimated']})"
    if weight > 0.05:
        desc += f" — Consider hedging or reducing before report ({weight:.0%} of portfolio)"
    # ... append event ...
    earn_count += 1
```

**Rationale**: The `description` field is already the primary user-facing text. Appending a brief recommendation when `actionRequired` is true gives users context without needing a separate field.

### Step 7: Increase max_events budget with macro slot guarantee

With 6 source types, the current `max_events=8` default will cut off useful items. Increase to `max_events=12`.

**Change**: `build_market_events()` signature default: `max_events: int = 12`

Source budgets (before global sort+truncation):
- News: `[:6]` (unchanged)
- Earnings: `[:4]` (unchanged)
- Economic: `[:3]` (new)
- Dividends: `[:3]` (new)
- Estimate revisions: `[:2]` (new)
- Insider signals: `[:2]` (new)
- Total candidates: up to 20, truncated to 12 by two-pool merge

**Macro slot guarantee**: Economic/Fed events use a fixed relevance of 70 (no portfolio weight), so a portfolio with many high-weight company events could crowd them out entirely. To prevent this, the final truncation uses a two-pool merge instead of a flat sort:

```python
# --- Final truncation with macro slot guarantee ---
_MACRO_TYPES = {"economic", "fed"}
MIN_MACRO_SLOTS = 2
max_events = max(0, max_events)  # clamp to prevent negative slicing

macro_events = [e for e in events if e["type"] in _MACRO_TYPES]
company_events = [e for e in events if e["type"] not in _MACRO_TYPES]

macro_events.sort(key=lambda e: e.get("relevance", 0), reverse=True)
company_events.sort(key=lambda e: e.get("relevance", 0), reverse=True)

# Reserve up to MIN_MACRO_SLOTS for macro events, clamped to max_events
macro_cap = min(MIN_MACRO_SLOTS, len(macro_events), max_events)
macro_reserved = macro_events[:macro_cap]
macro_overflow = macro_events[macro_cap:]

# Remaining slots: company events + any overflow macro compete by relevance
remaining_budget = max_events - len(macro_reserved)  # always >= 0 since macro_cap <= max_events
overflow_pool = sorted(
    company_events + macro_overflow,
    key=lambda e: e.get("relevance", 0),
    reverse=True,
)
remaining_take = overflow_pool[:remaining_budget]

events = sorted(
    macro_reserved + remaining_take,
    key=lambda e: e.get("relevance", 0),
    reverse=True,
)
```

This guarantees up to 2 macro event slots even when company events dominate. If fewer than 2 macro events exist, the extra slots go to company events. Any 3rd+ macro event competes with company events by relevance for remaining slots. The `max(0, ...)` guard prevents negative slicing if `max_events` is ever set below `MIN_MACRO_SLOTS`. The final list is sorted by relevance for display order.

---

## Impacted Files

| File | Change |
|------|--------|
| `mcp_tools/news_events.py` | Steps 1-7: `_load_portfolio_weights()` refactor, new imports, constants, 4 new event blocks, enriched descriptions, max_events bump + macro slot guarantee |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | Add `"dividend"` to type union, add `ticker?: string` |
| `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` | Add `"dividend"` to type union, add `ticker?: string` (line 4, duplicate `MarketEvent`) |
| `frontend/packages/chassis/src/catalog/types.ts` | Add `"dividend"` to type union, add `ticker?: string` (line 377, duplicate `MarketEvent`) |
| `frontend/packages/connectors/src/resolver/registry.ts` | Pass through `ticker` in `transformMarketEvents()` |
| `tests/mcp_tools/test_news_events_builder.py` | NEW — unit tests for `build_market_events()` |
| `tests/mcp_tools/test_news_events_portfolio.py` | Update existing tests — `_load_portfolio_weights()` now returns tuples |
| `frontend/packages/connectors/src/features/positions/__tests__/useMarketIntelligence.test.tsx` | Update test for `ticker` passthrough and `"dividend"` type |

No changes to:
- `routes/positions.py` — passes through `build_market_events()` output, no shape change
- `MarketIntelligenceBanner.tsx` — renders `event.type.toUpperCase()` as badge, auto-displays "DIVIDEND"

## Tests

**File**: `tests/mcp_tools/test_news_events_builder.py` (NEW)

Unit tests for `build_market_events()` with monkeypatched FMP responses:

1. **Economic events — High-impact only**: Mock `get_economic_data` returning High + Low items → only High appears
2. **Economic events — distinct same-day events preserved**: Mock 2 High-impact events on same date (FOMC + Nonfarm Payrolls) → both surface (no date-based dedup)
3. **Economic events — Fed classification**: Mock event with "FOMC" in name → `type: "fed"`
4. **Economic events — failure graceful**: Mock `get_economic_data` raising → no crash, other events still present
5. **Economic events — use_cache threaded**: Verify `use_cache` kwarg is passed through to `get_economic_data`
6. **Dividend events — weight-based relevance**: Mock `get_portfolio_events_calendar` with dividends → relevance scales with weight
7. **Dividend events — description includes amount**: Mock with `dividend` field → "$X/share" in description
8. **Dividend events — zero-weight filtered**: Mock dividend for ticker not in portfolio weights → event not included
9. **Estimate revisions — downward large position**: Mock `screen_estimate_revisions` returning down revision on >5% position → `actionRequired: True`, "Review thesis" in description
10. **Estimate revisions — skip tiny positions**: Mock revision on <2% position → not included
11. **Estimate revisions — skip flat direction**: Mock revision with `direction="flat"` → not included
12. **Estimate revisions — failure graceful**: Mock raising → no crash
13. **Insider selling — large position**: Mock `get_insider_trades` with recent_trades containing 3 sells + 1 buy within 90 days on >5% holding → negative impact event with "Monitor" prompt and "As of {date}" timeframe
14. **Insider balanced — not surfaced**: Mock recent_trades with equal buys and sells → no insider event generated
15. **Insider — only top 3 equities checked**: Mock 10 holdings (mix of equity + ETF) → only top 3 equities by weight call `get_insider_trades`, ETFs skipped
16. **Insider — use_cache threaded**: Verify `use_cache` kwarg is passed through to `get_insider_trades`
17. **News action enrichment**: Mock high-weight ticker news → description includes "Review X position"
18. **Earnings action enrichment**: Mock high-weight earnings → description includes "Consider hedging"
19. **Max events cap + sort order**: Mock all 6 sources returning many items → output capped at 12, sorted by relevance descending
20. **Economic events — nearest first**: Mock events on multiple dates → sorted ascending, nearest date surfaces first
21. **Economic events — Fed sorts first on same day**: Mock CPI + FOMC on same date → FOMC appears first in output (Fed priority in sort key), both included since no date dedup
22. **Portfolio weights refactor**: Verify `_load_portfolio_weights()` returns `(weight, type)` tuples and callers unpack correctly
23. **Portfolio weights type collision**: Mock same fmp_ticker with "equity" + "etf" types → merged type is "equity"
24. **Dividend action enrichment**: Mock high-weight dividend → description includes "Review position ahead of ex-date" + `actionRequired: True`
25. **Estimate revisions — portfolio-weighted ranking**: Mock 3 revisions: (ticker A: 2% weight, eps_delta=0.50), (ticker B: 15% weight, eps_delta=0.10), (ticker C: 1% weight, eps_delta=0.80) → ticker B surfaces first (0.15×0.10=0.015 > 0.02×0.50=0.010), ticker C excluded (<2% weight)
26. **Estimate revisions — revenue_delta fallback**: Mock revision with `eps_delta=None`, `revenue_delta=5.0`, weight 10% → `_portfolio_impact = 0.10 * 5.0 = 0.50`, event surfaces correctly (not buried at impact 0)
27. **Macro slot guarantee — company events don't crowd out macro**: Mock 15 company events (relevance 80-95) + 2 economic events (relevance 70) → both economic events present in final 12
28. **Macro slot guarantee — no macro events**: Mock 15 company events + 0 economic → all 12 slots go to company events (no empty macro reservation)
29. **Macro slot guarantee — overflow macro competes**: Mock 4 macro events (relevance 70, 65, 90, 50) + 5 company events (relevance 60 each), max_events=6 → macro sorted by relevance → 2 reserved (90, 70), overflow (65, 50) competes with 5 company for 4 remaining slots → the relevance-65 overflow macro beats the relevance-60 company events and makes the cut
30. **Macro slot guarantee — max_events=1**: Mock 2 macro + 3 company, max_events=1 → only 1 macro reserved (macro_cap clamped), 0 remaining budget, total output is 1 event
31. **Economic impact case-insensitive**: Mock event with `impact: "HIGH"` → included (case-insensitive check)
32. **Estimate revisions — ETFs excluded**: Mock portfolio with SPY (etf, 20% weight) + AAPL (equity, 10% weight) → `screen_estimate_revisions` called with `["AAPL"]` only, SPY excluded
33. **Estimate revisions — eps_delta=0.0 does not fall through**: Mock revision with `eps_delta=0.0`, `revenue_delta=5.0` → `_portfolio_impact` uses `0.0` (eps_delta), NOT `5.0` (revenue_delta). `is not None` check prevents falsy zero fallthrough
34. **Earnings — zero-weight filtered**: Mock earnings calendar returning ticker not in portfolio weights → event not included (same guard as dividends)
35. **Earnings — eps_estimated=0.0 included**: Mock earnings with `eps_estimated=0.0` → description includes "(EPS est: $0.0)", not omitted
36. **Insider — stale trades skipped**: Mock `get_insider_trades` with all recent_trades older than 90 days → `recent_sells=0`, insider event not surfaced
37. **Insider — trades within lookback counted**: Mock recent_trades: 2 sells at day 30 + 1 sell at day 120 → only 2 sells counted (the day-120 trade is past cutoff, loop breaks early since trades sorted descending)

---

## Performance Considerations

| Source | API Calls | Latency | Notes |
|--------|-----------|---------|-------|
| News | 1 FMP call | ~500ms | Existing, cached |
| Earnings | 1 FMP call | ~500ms | Existing, cached |
| Economic | 1 FMP call | ~500ms | New, cached |
| Dividends | 1 FMP call | ~500ms | New, cached |
| Estimates | 1 HTTP call | ~1s | New, hosted API batch call |
| Insider | Up to 6 FMP calls (2 per symbol × 3 symbols) | ~1.5s worst case | New, internal parallelization per symbol |

Total worst-case latency: ~4.5s (up from ~1s). This runs in `run_in_threadpool` from the API endpoint, so it doesn't block the event loop. The frontend already handles loading state for this endpoint.

If insider call latency is problematic, it can be reduced to top 2 holdings or the calls can be parallelized across symbols with `ThreadPoolExecutor`.

---

## Not In Scope

- **`probability` field** — FMP doesn't provide probability data. Leave unpopulated.
- **Technical signals** (price/volume breakouts) — would require computed data or IBKR market data. Backlog.
- **Geopolitical events** — no structured data source available. Backlog.
- **Institutional ownership** — per-ticker API like insider trades, but ownership changes are quarterly (13F filings). Too infrequent for a real-time feed. Could revisit as a quarterly alert.
- **Insider share volumes** — FMP's `insider_trade_statistics` returns transaction counts (`totalBuys`/`totalSells`), not share volumes. To get share-level data would require summing from individual trade records. Current approach uses transaction count ratio which is sufficient for a signal.
- **API endpoint changes** — `routes/positions.py` is a thin passthrough, no shape changes needed.
